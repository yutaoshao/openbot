#[path = "service_protocol.rs"]
mod service_protocol;
use service_protocol::verified_port;
pub use service_protocol::{web_console_url, Connection, InstanceLease};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

const START_TIMEOUT: Duration = Duration::from_secs(45);
const STOP_TIMEOUT: Duration = Duration::from_secs(10);
const POLL_INTERVAL: Duration = Duration::from_millis(50);
const RESTART_EXIT_CODE: i32 = 75;

fn random_secret() -> Result<String, String> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes)
        .map_err(|error| format!("Cannot create service identity: {error}"))?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

struct Instance {
    id: String,
    token: String,
    ready_file: PathBuf,
    deadline: Instant,
}

enum ServiceExit {
    Restart,
    Shutdown,
}

struct Worker {
    stop: mpsc::Sender<()>,
    handle: JoinHandle<()>,
}

pub struct ServiceManager {
    last_graceful_stop: AtomicBool,
    resources: PathBuf,
    data: PathBuf,
    connection: Mutex<Connection>,
    worker: Mutex<Option<Worker>>,
    notify: Box<dyn Fn(&str) + Send + Sync>,
}

impl ServiceManager {
    pub fn new(
        resources: PathBuf,
        data: PathBuf,
        notify: impl Fn(&str) + Send + Sync + 'static,
    ) -> Arc<Self> {
        Arc::new(Self {
            last_graceful_stop: AtomicBool::new(false),
            resources,
            data,
            connection: Mutex::new(Connection::starting()),
            worker: Mutex::new(None),
            notify: Box::new(notify),
        })
    }

    pub fn snapshot(&self) -> Connection {
        self.connection.lock().unwrap().clone()
    }

    fn update(&self, connection: Connection) {
        let status = connection.status;
        *self.connection.lock().unwrap() = connection;
        (self.notify)(status);
    }

    pub fn start(self: &Arc<Self>, retry: bool) -> Result<(), String> {
        let mut worker = self.worker.lock().unwrap();
        if worker.is_some() {
            if !retry || self.snapshot().status != "failed" {
                return Err("Only a failed, stopped service can be retried".into());
            }
        }
        if let Some(previous) = worker.take() {
            let _ = previous.handle.join();
        }
        self.update(Connection::starting());
        let (stop, receiver) = mpsc::channel();
        let manager = Arc::clone(self);
        let handle = thread::spawn(move || manager.supervise(receiver));
        *worker = Some(Worker { stop, handle });
        Ok(())
    }

    pub fn shutdown(&self) {
        // Only the worker owns the Child. Never locate or kill a process by port/PID.
        if let Some(worker) = self.worker.lock().unwrap().take() {
            let _ = worker.stop.send(());
            if worker.handle.join().is_err() {
                self.last_graceful_stop.store(false, Ordering::SeqCst);
            }
        }
        self.update(Connection::failed("Service stopped".into()));
    }

    pub fn shutdown_for_update(&self) -> Result<(), String> {
        self.shutdown();
        if self.last_graceful_stop.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err("Python did not stop before the deadline; update was not installed".into())
        }
    }

    fn supervise(&self, stop: mpsc::Receiver<()>) {
        loop {
            if stop.try_recv().is_ok() {
                return;
            }
            match self.run_instance(&stop) {
                Ok(ServiceExit::Restart) => self.update(Connection::starting()),
                Ok(ServiceExit::Shutdown) => return,
                Err(error) => {
                    self.update(Connection::failed(error));
                    return;
                }
            }
        }
    }

    fn run_instance(&self, stop: &mpsc::Receiver<()>) -> Result<ServiceExit, String> {
        let instance_id = random_secret()?;
        let token = random_secret()?;
        let run_dir = self.data.join("run");
        fs::create_dir_all(&run_dir).map_err(|error| error.to_string())?;
        fs::set_permissions(&run_dir, fs::Permissions::from_mode(0o700))
            .map_err(|error| error.to_string())?;
        let ready_file = run_dir.join(format!("{instance_id}.json"));
        let instance = Instance {
            id: instance_id,
            token,
            ready_file,
            deadline: Instant::now() + START_TIMEOUT,
        };
        let mut child = self.launch(&instance)?;
        let outcome = self.monitor(&mut child, stop, &instance);
        self.last_graceful_stop
            .store(stop_child(&mut child, STOP_TIMEOUT), Ordering::SeqCst);
        let _ = fs::remove_file(instance.ready_file);
        outcome
    }

    fn launch(&self, instance: &Instance) -> Result<Child, String> {
        let runtime = self.resources.join("runtime");
        let python = runtime.join("bin/python3");
        let script = self.resources.join("service_entry.py");
        if !python.is_file() || !script.is_file() {
            return Err(
                "Bundled Python service is missing; rebuild the application resources".into(),
            );
        }
        let logs = self.data.join("logs");
        fs::create_dir_all(&logs).map_err(|error| error.to_string())?;
        let log = OpenOptions::new()
            .create(true)
            .append(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(logs.join("desktop-service.log"))
            .map_err(|error| error.to_string())?;
        log.set_permissions(fs::Permissions::from_mode(0o600))
            .map_err(|error| error.to_string())?;
        let mut command = Command::new(python);
        command
            .args(["-I", "-B"])
            .arg(script)
            .arg("--data-dir")
            .arg(&self.data)
            .arg("--ready-file")
            .arg(&instance.ready_file)
            .arg("--resource-dir")
            .arg(&runtime)
            .current_dir(&self.data)
            .env_clear()
            .env(
                "PATH",
                format!(
                    "{}:/usr/bin:/bin:/usr/sbin:/sbin",
                    runtime.join("bin").display()
                ),
            )
            .env("OPENBOT_DESKTOP_TOKEN", &instance.token)
            .env("OPENBOT_DESKTOP_INSTANCE_ID", &instance.id)
            .env("PYTHON_DOTENV_DISABLED", "1")
            .env("TIKTOKEN_CACHE_DIR", runtime.join("tokenizer-cache"))
            .stdin(Stdio::piped())
            .stdout(log.try_clone().map_err(|error| error.to_string())?)
            .stderr(log);
        for key in ["HOME", "TMPDIR", "LANG", "LC_CTYPE"] {
            if let Some(value) = std::env::var_os(key) {
                command.env(key, value);
            }
        }
        command
            .spawn()
            .map_err(|error| format!("Cannot launch bundled service: {error}"))
    }

    fn monitor(
        &self,
        child: &mut Child,
        stop: &mpsc::Receiver<()>,
        instance: &Instance,
    ) -> Result<ServiceExit, String> {
        let mut ready = false;
        loop {
            if stop.try_recv().is_ok() {
                return Ok(ServiceExit::Shutdown);
            }
            if let Some(status) = child.try_wait().map_err(|error| error.to_string())? {
                if status.code() == Some(RESTART_EXIT_CODE) {
                    return Ok(ServiceExit::Restart);
                }
                return Err(format!(
                    "Bundled service exited ({status}); see desktop-service.log"
                ));
            }
            if !ready {
                if let Some(port) = verified_port(&instance.ready_file, &instance.id, child.id())? {
                    self.update(Connection {
                        status: "ready",
                        base_url: Some(format!("http://127.0.0.1:{port}")),
                        instance_id: Some(instance.id.clone()),
                        token: Some(instance.token.clone()),
                        error: None,
                    });
                    ready = true;
                } else if Instant::now() >= instance.deadline {
                    return Err("Bundled service did not become ready within 45 seconds; see desktop-service.log".into());
                }
            }
            thread::sleep(POLL_INTERVAL);
        }
    }
}

fn stop_child(child: &mut Child, timeout: Duration) -> bool {
    if let Ok(Some(status)) = child.try_wait() {
        let _ = child.wait();
        return status.success();
    }
    if let Some(mut stdin) = child.stdin.take() {
        let _ = stdin.write_all(b"shutdown\n");
    }
    let started = Instant::now();
    while started.elapsed() < timeout {
        if let Ok(Some(status)) = child.try_wait() {
            let _ = child.wait();
            return status.success();
        }
        thread::sleep(Duration::from_millis(20));
    }
    let _ = child.kill();
    let _ = child.wait();
    false
}

#[cfg(test)]
#[path = "service_tests.rs"]
mod tests;
