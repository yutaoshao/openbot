//! Only compiled-in release policy can select an update source or trust key.
use crate::service::ServiceManager;
use crate::update_protocol::{bundle_fingerprint, bundle_root, gate_url, secure_endpoint};
use serde::Serialize;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::Manager;
use tauri_plugin_updater::{Update, UpdaterExt};

#[derive(Default)]
pub struct UpdateState {
    busy: AtomicBool,
    recovery_required: AtomicBool,
    pending: Mutex<Option<Update>>,
}

struct Operation<'a>(&'a UpdateState);
impl Drop for Operation<'_> {
    fn drop(&mut self) {
        self.0.busy.store(false, Ordering::SeqCst);
    }
}
impl UpdateState {
    pub fn recovery_required(&self) -> bool {
        self.recovery_required.load(Ordering::SeqCst)
    }
    fn claim(&self) -> Result<Operation<'_>, String> {
        self.busy
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .map_err(|_| "An update operation is already running".to_string())?;
        Ok(Operation(self))
    }
}

#[derive(Serialize)]
pub struct UpdateStatus {
    status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    notes: Option<String>,
}

#[tauri::command]
pub async fn desktop_check_update(app: tauri::AppHandle) -> Result<UpdateStatus, String> {
    let state = app.state::<UpdateState>();
    let _operation = state.claim()?;
    *state.pending.lock().unwrap() = None;
    let (Some(endpoint), Some(public_key)) = (
        option_env!("OPENBOT_UPDATE_ENDPOINT"),
        option_env!("OPENBOT_UPDATE_PUBLIC_KEY"),
    ) else {
        return Ok(UpdateStatus {
            status: "unconfigured",
            version: None,
            notes: None,
        });
    };
    if endpoint.trim().is_empty() || public_key.trim().is_empty() {
        return Ok(UpdateStatus {
            status: "unconfigured",
            version: None,
            notes: None,
        });
    }
    let endpoint = secure_endpoint(endpoint)?;
    let update = app
        .updater_builder()
        .endpoints(vec![endpoint])
        .map_err(|e| e.to_string())?
        .pubkey(public_key)
        .timeout(Duration::from_secs(30))
        .configure_client(|client| {
            client
                .https_only(true)
                .redirect(reqwest::redirect::Policy::limited(5))
        })
        .build()
        .map_err(|_| "Release update configuration is invalid".to_string())?
        .check()
        .await
        .map_err(|_| "Could not check for updates; try again later".to_string())?;
    let status = if let Some(update) = update.as_ref() {
        secure_endpoint(update.download_url.as_str())?;
        UpdateStatus {
            status: "available",
            version: Some(update.version.clone()),
            notes: update.body.clone(),
        }
    } else {
        UpdateStatus {
            status: "current",
            version: None,
            notes: None,
        }
    };
    *state.pending.lock().unwrap() = update;
    Ok(status)
}

async fn gate(
    connection: &crate::service::Connection,
    action: &str,
    lease: Option<&str>,
) -> Result<serde_json::Value, String> {
    let (url, token) = gate_url(connection, action)?;
    let response = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|_| "Cannot create service control client")?
        .post(url)
        .bearer_auth(token)
        .json(&serde_json::json!({"lease": lease}))
        .send()
        .await
        .map_err(|_| "Cannot contact the owned Python service".to_string())?;
    if response.status() == reqwest::StatusCode::CONFLICT {
        return Err("OpenBot has active work or configuration changes; finish them and try installing again".into());
    }
    if !response.status().is_success() {
        return Err("Python service refused the update transition".into());
    }
    response
        .json()
        .await
        .map_err(|_| "Invalid update transition response".into())
}

async fn abort_transition(
    connection: &crate::service::Connection,
    lease: &str,
    cause: &str,
) -> String {
    if gate(connection, "resume", Some(lease)).await.is_ok() {
        format!("{cause}; update was not installed and service admission was restored")
    } else {
        format!("{cause}; update was not installed but service admission recovery could not be confirmed. Quit and reopen OpenBot")
    }
}

#[tauri::command]
pub async fn desktop_install_update(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let state = app.state::<UpdateState>();
    let _operation = state.claim()?;
    if state.recovery_required() {
        return Err("Reinstall the signed app before retrying an update".into());
    }
    let mut update = state
        .pending
        .lock()
        .unwrap()
        .take()
        .ok_or("Check for an available update first")?;
    update.timeout = Some(Duration::from_secs(300));
    // Signature and signed version are verified before asking the service to quiesce.
    let bytes = match update.download(|_, _| {}, || {}).await {
        Ok(bytes) => bytes,
        Err(_) => {
            *state.pending.lock().unwrap() = Some(update);
            return Err(
                "Update download or signature verification failed; the running service was kept"
                    .into(),
            );
        }
    };
    let manager = app.state::<Arc<ServiceManager>>().inner().clone();
    let lifecycle = app.state::<crate::lifecycle::Lifecycle>();
    let installation = lifecycle.begin_install()?;
    let connection = manager.snapshot();
    let mut random = [0_u8; 32];
    getrandom::fill(&mut random).map_err(|_| "Cannot create update transition identity")?;
    let transition = random
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    let prepared = match gate(&connection, "prepare", Some(&transition)).await {
        Ok(value) => value,
        Err(error) => {
            *state.pending.lock().unwrap() = Some(update);
            if error.starts_with("OpenBot has active work") {
                return Err(error);
            }
            return Err(abort_transition(&connection, &transition, &error).await);
        }
    };
    let lease = transition;
    if prepared["lease"].as_str() != Some(&lease) {
        return Err(abort_transition(&connection, &lease, "Invalid update transition lease").await);
    }
    let root = match bundle_root() {
        Ok(root) => root,
        Err(error) => {
            return Err(abort_transition(&connection, &lease, &error).await);
        }
    };
    let fingerprint_root = root.clone();
    let before =
        match tauri::async_runtime::spawn_blocking(move || bundle_fingerprint(&fingerprint_root))
            .await
        {
            Ok(Ok(value)) => value,
            _ => {
                return Err(
                    abort_transition(&connection, &lease, "Cannot verify current bundle").await,
                );
            }
        };
    if manager.snapshot().instance_id != connection.instance_id {
        return Err(abort_transition(&connection, &lease, "The service instance changed").await);
    }
    let stop_manager = manager.clone();
    if tauri::async_runtime::spawn_blocking(move || stop_manager.shutdown_for_update())
        .await
        .map_err(|_| "Service shutdown failed".to_string())?
        .is_err()
    {
        let _ = manager.start(true);
        return Err("Python could not stop cleanly; update was not installed. Check service status before retrying".into());
    }
    state.recovery_required.store(true, Ordering::SeqCst);
    let result = tauri::async_runtime::spawn_blocking(move || {
        let result = update.install(&bytes);
        let restored =
            result.is_err() && bundle_fingerprint(&root).is_ok_and(|after| after == before);
        (result, restored)
    })
    .await
    .map_err(|_| {
        "Installer interrupted; service remains stopped. Quit and reopen OpenBot".to_string()
    })?;
    match result {
        (Ok(()), _) => {
            installation.complete();
            let restart_app = app.clone();
            std::thread::spawn(move || restart_app.restart());
            Ok(serde_json::json!({"status": "restarting"}))
        }
        (Err(_), true) => {
            state.recovery_required.store(false, Ordering::SeqCst);
            manager.start(true).map_err(|_| "Installation failed; old bundle is intact but service restart failed. Reopen OpenBot".to_string())?;
            Err("Installation failed; the previous bundle was verified intact and its service is restarting".into())
        }
        (Err(_), false) => Err("Installation failed and the previous bundle could not be verified. Service remains stopped; reinstall the signed app while keeping application data".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn update_operations_are_exclusive_and_release_after_failure() {
        let state = UpdateState::default();
        let operation = state.claim().unwrap();
        assert!(state.claim().is_err());
        drop(operation);
        assert!(state.claim().is_ok());
    }
}
