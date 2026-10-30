mod lifecycle;
mod service;
mod update;
mod update_protocol;

use service::{web_console_url, Connection, InstanceLease, ServiceManager};
use std::process::{Command, Stdio};
use std::sync::Arc;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::Manager;
use tauri_plugin_autostart::ManagerExt;
use tauri_plugin_dialog::DialogExt;

#[cfg(not(all(target_os = "macos", target_arch = "aarch64")))]
compile_error!("OpenBot desktop currently supports Apple Silicon macOS only.");

fn show_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn request_quit(app: &tauri::AppHandle) {
    if !app.state::<lifecycle::Lifecycle>().request_quit() {
        return;
    }
    let app = app.clone();
    std::thread::spawn(move || {
        app.state::<Arc<ServiceManager>>().shutdown();
        if app.state::<lifecycle::Lifecycle>().finish_quit() {
            app.exit(0);
        }
    });
}

#[tauri::command]
fn desktop_connection(state: tauri::State<'_, Arc<ServiceManager>>) -> Connection {
    state.snapshot()
}

#[tauri::command]
async fn desktop_open_web(state: tauri::State<'_, Arc<ServiceManager>>) -> Result<(), String> {
    let url = web_console_url(&state.snapshot())?;
    tauri::async_runtime::spawn_blocking(move || {
        let status = Command::new("/usr/bin/open")
            .arg(url)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|_| "Cannot open the local Web console".to_string())?;
        if status.success() {
            Ok(())
        } else {
            Err("Cannot open the local Web console".into())
        }
    })
    .await
    .map_err(|_| "Cannot open the local Web console".to_string())?
}

#[tauri::command]
fn desktop_retry(app: tauri::AppHandle) -> Result<(), String> {
    if app.state::<update::UpdateState>().recovery_required() {
        return Err("Previous update recovery could not be verified; reinstall the signed app while keeping application data".into());
    }
    app.state::<lifecycle::Lifecycle>()
        .retry_service(|| app.state::<Arc<ServiceManager>>().start(true))
}

#[tauri::command]
fn desktop_quit(app: tauri::AppHandle) {
    request_quit(&app);
}

#[tauri::command]
fn desktop_autostart(app: tauri::AppHandle) -> Result<bool, String> {
    app.autolaunch()
        .is_enabled()
        .map_err(|error| error.to_string())
}

#[tauri::command]
async fn desktop_choose_directory(app: tauri::AppHandle) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .blocking_pick_folder()
            .map(|selected| {
                let path = selected.into_path().map_err(|error| error.to_string())?;
                path.to_str()
                    .map(str::to_owned)
                    .ok_or_else(|| "Selected directory must have a valid UTF-8 path".to_string())
            })
            .transpose()
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
fn desktop_set_autostart(app: tauri::AppHandle, enabled: bool) -> Result<bool, String> {
    let launcher = app.autolaunch();
    if enabled {
        launcher.enable()
    } else {
        launcher.disable()
    }
    .map_err(|error| error.to_string())?;
    launcher.is_enabled().map_err(|error| error.to_string())
}

fn setup_service(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let data = app.path().app_data_dir()?;
    app.manage(InstanceLease::acquire(&data)?);
    let status = MenuItem::with_id(app, "status", "OpenBot: starting", false, None::<&str>)?;
    let show = MenuItem::with_id(app, "show", "打开 OpenBot", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "退出 OpenBot", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&status, &show, &quit])?;
    TrayIconBuilder::with_id("openbot")
        .icon(tauri::image::Image::from_bytes(include_bytes!(
            "../icons/icon.png"
        ))?)
        .tooltip("OpenBot")
        .menu(&menu)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => show_main(app),
            "quit" => request_quit(app),
            _ => (),
        })
        .build(app)?;
    let handle = app.handle().clone();
    let manager = ServiceManager::new(app.path().resource_dir()?, data, move |state| {
        let text = format!("OpenBot: {state}");
        let status = status.clone();
        // Do not make a supervisor thread wait for UI work while quit/retry joins it.
        let _ = handle.run_on_main_thread(move || {
            let _ = status.set_text(text);
        });
    });
    app.manage(Arc::clone(&manager));
    manager.start(false)?;
    if std::env::args().any(|argument| argument == "--background") {
        if let Some(window) = app.get_webview_window("main") {
            window.hide()?;
        }
    }
    Ok(())
}

fn main() {
    tauri::Builder::default()
        // The single-instance plugin must precede plugins that initialize app state.
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            show_main(app)
        }))
        .plugin(
            tauri_plugin_autostart::Builder::new()
                .app_name("OpenBot")
                .macos_launcher(tauri_plugin_autostart::MacosLauncher::LaunchAgent)
                .arg("--background")
                .build(),
        )
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(update::UpdateState::default())
        .manage(lifecycle::Lifecycle::default())
        .setup(setup_service)
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            desktop_connection,
            desktop_retry,
            desktop_quit,
            desktop_autostart,
            desktop_set_autostart,
            desktop_choose_directory,
            desktop_open_web,
            update::desktop_check_update,
            update::desktop_install_update
        ])
        .build(tauri::generate_context!())
        .expect("Failed to initialize OpenBot desktop")
        .run(|app, event| match event {
            tauri::RunEvent::ExitRequested { api, .. } => {
                if !app.state::<lifecycle::Lifecycle>().exit_ready() {
                    api.prevent_exit();
                    request_quit(app);
                }
            }
            tauri::RunEvent::Exit => app.state::<Arc<ServiceManager>>().shutdown(),
            tauri::RunEvent::Reopen { .. } => show_main(app),
            _ => (),
        });
}
