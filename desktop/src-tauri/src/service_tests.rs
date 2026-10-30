use super::*;
use std::path::Path;
use tempfile::{tempdir, TempDir};

fn handshake(directory: &Path, value: serde_json::Value) -> PathBuf {
    let path = directory.join("ready.json");
    fs::write(&path, value.to_string()).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    path
}

#[test]
fn instance_lease_fails_closed_until_original_owner_releases_it() {
    let directory = tempdir().unwrap();
    let first = InstanceLease::acquire(directory.path()).unwrap();
    assert!(InstanceLease::acquire(directory.path()).is_err());
    drop(first);
    assert!(InstanceLease::acquire(directory.path()).is_ok());
}

#[test]
fn web_console_url_uses_only_verified_local_connection_and_secret_fragment() {
    let connection = Connection {
        status: "ready",
        base_url: Some("http://127.0.0.1:43210".into()),
        instance_id: Some("a".repeat(64)),
        token: Some("b".repeat(64)),
        error: None,
    };
    assert_eq!(
        web_console_url(&connection).unwrap(),
        format!(
            "http://127.0.0.1:43210/#openbot-desktop-token={}",
            "b".repeat(64)
        )
    );
    assert!(web_console_url(&Connection::starting()).is_err());
    assert!(web_console_url(&Connection::failed("synthetic".into())).is_err());
    for base in [
        "http://localhost:43210",
        "https://127.0.0.1:43210",
        "http://127.0.0.2:43210",
        "http://127.0.0.1:0",
        "http://127.0.0.1:65536",
        "http://127.0.0.1:43210/path",
        "http://127.0.0.1:43210?query=1",
        "http://127.0.0.1:43210@evil.invalid",
        "http://127.0.0.1:+43210",
    ] {
        assert!(web_console_url(&Connection {
            base_url: Some(base.into()),
            ..connection.clone()
        })
        .is_err());
    }
    assert!(web_console_url(&Connection {
        instance_id: None,
        ..connection.clone()
    })
    .is_err());
    assert!(web_console_url(&Connection {
        token: Some("invalid#fragment".into()),
        ..connection
    })
    .is_err());
}

#[test]
fn handshake_binds_protocol_identity_pid_and_nonzero_port() {
    let directory = tempdir().unwrap();
    let value = serde_json::json!({"protocol_version":1,"instance_id":"ours","pid":123,"port":456});
    let path = handshake(directory.path(), value.clone());
    assert_eq!(verified_port(&path, "ours", 123).unwrap(), Some(456));
    assert!(verified_port(&path, "other", 123).is_err());
    assert!(verified_port(&path, "ours", 124).is_err());
    for (field, invalid) in [("protocol_version", 2), ("port", 0), ("port", 65536)] {
        let mut candidate = value.clone();
        candidate[field] = invalid.into();
        let path = handshake(directory.path(), candidate);
        assert!(verified_port(&path, "ours", 123).is_err());
    }
}

#[test]
fn handshake_rejects_unsafe_permissions_symlinks_and_oversized_data() {
    let directory = tempdir().unwrap();
    let path = handshake(directory.path(), serde_json::json!({}));
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
    assert!(verified_port(&path, "ours", 1)
        .unwrap_err()
        .contains("0600"));
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    fs::write(&path, vec![b' '; 4097]).unwrap();
    assert!(verified_port(&path, "ours", 1)
        .unwrap_err()
        .contains("size"));
    let link = directory.path().join("link.json");
    std::os::unix::fs::symlink(&path, &link).unwrap();
    assert!(verified_port(&link, "ours", 1).is_err());
    assert_eq!(
        verified_port(&directory.path().join("absent"), "ours", 1).unwrap(),
        None
    );
}

fn assert_reaped(pid: u32) {
    let alive = Command::new("/bin/kill")
        .args(["-0", &pid.to_string()])
        .stderr(Stdio::null())
        .status()
        .unwrap();
    assert!(!alive.success(), "owned child must be reaped");
}

#[test]
fn shutdown_sends_exact_line_and_allows_orderly_exit() {
    let mut child = Command::new("/bin/sh")
        .args(["-c", "IFS= read -r line; test \"$line\" = shutdown"])
        .stdin(Stdio::piped())
        .spawn()
        .unwrap();
    let pid = child.id();
    assert!(stop_child(&mut child, Duration::from_secs(1)));
    assert!(child.wait().unwrap().success());
    assert_reaped(pid);
}

#[test]
fn shutdown_timeout_kills_only_owned_child_and_can_repeat() {
    let mut child = Command::new("/bin/sleep")
        .arg("30")
        .stdin(Stdio::piped())
        .spawn()
        .unwrap();
    let mut unrelated = Command::new("/bin/sleep").arg("30").spawn().unwrap();
    let pid = child.id();
    assert!(!stop_child(&mut child, Duration::from_millis(30)));
    stop_child(&mut child, Duration::from_millis(30));
    assert_reaped(pid);
    assert!(unrelated.try_wait().unwrap().is_none());
    unrelated.kill().unwrap();
    unrelated.wait().unwrap();
}

fn fake_service(body: &str) -> (TempDir, Arc<ServiceManager>) {
    let directory = tempdir().unwrap();
    let resources = directory.path().join("resources");
    fs::create_dir_all(resources.join("runtime/bin")).unwrap();
    let python = resources.join("runtime/bin/python3");
    fs::write(&python, "#!/bin/sh\nshift 2\nexec /bin/sh \"$@\"\n").unwrap();
    fs::set_permissions(&python, fs::Permissions::from_mode(0o700)).unwrap();
    fs::write(resources.join("service_entry.py"), body).unwrap();
    let manager = ServiceManager::new(resources, directory.path().join("data"), |_| {});
    (directory, manager)
}

const READY: &str = r#"
ready="$4"
printf '{"protocol_version":1,"instance_id":"%s","pid":%s,"port":12345}' "$OPENBOT_DESKTOP_INSTANCE_ID" "$$" > "$ready.tmp"
chmod 600 "$ready.tmp"
mv "$ready.tmp" "$ready"
"#;

fn wait_for(manager: &ServiceManager, expected: &str) -> Connection {
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        let snapshot = manager.snapshot();
        if snapshot.status == expected {
            return snapshot;
        }
        assert!(
            Instant::now() < deadline,
            "waiting for {expected}, got {}",
            snapshot.status
        );
        thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn service_publishes_only_its_handshake_and_clears_connection_after_crash() {
    let body = format!("{READY}\nsleep 0.3\nexit 9\n");
    let (_directory, manager) = fake_service(&body);
    manager.start(false).unwrap();
    let ready = wait_for(&manager, "ready");
    assert_eq!(ready.base_url.as_deref(), Some("http://127.0.0.1:12345"));
    assert_eq!(ready.token.as_ref().unwrap().len(), 64);
    assert_eq!(ready.instance_id.as_ref().unwrap().len(), 64);
    let serialized = serde_json::to_value(&ready).unwrap();
    assert_eq!(
        serialized["instanceId"],
        ready.instance_id.as_ref().unwrap().as_str()
    );
    assert!(serialized.get("instance_id").is_none());
    assert!(
        manager.start(true).is_err(),
        "must not spawn a second ready service"
    );
    let failed = wait_for(&manager, "failed");
    assert!(failed.token.is_none() && failed.base_url.is_none());
    assert!(failed.instance_id.is_none());
    assert!(serde_json::to_value(&failed)
        .unwrap()
        .get("instanceId")
        .is_none());
    assert!(failed.error.unwrap().contains('9'));
    manager.shutdown();
}

#[test]
fn exit_75_rotates_identity_and_token_instead_of_reporting_a_crash() {
    let body = format!(
        r#"{READY}
if [ ! -e "$2/first-token" ]; then
  printf '%s' "$OPENBOT_DESKTOP_TOKEN" > "$2/first-token"
  printf '%s' "$OPENBOT_DESKTOP_INSTANCE_ID" > "$2/first-id"
  exit 75
fi
printf '%s' "$OPENBOT_DESKTOP_INSTANCE_ID" > "$2/second-id"
IFS= read -r line
"#
    );
    let (directory, manager) = fake_service(&body);
    manager.start(false).unwrap();
    let deadline = Instant::now() + Duration::from_secs(3);
    while !directory.path().join("data/second-id").exists() {
        assert!(Instant::now() < deadline);
        thread::sleep(Duration::from_millis(10));
    }
    let ready = wait_for(&manager, "ready");
    let data = directory.path().join("data");
    assert_eq!(
        ready.instance_id.as_ref().unwrap(),
        &fs::read_to_string(data.join("second-id")).unwrap()
    );
    assert_ne!(
        ready.instance_id.as_ref().unwrap(),
        &fs::read_to_string(data.join("first-id")).unwrap()
    );
    assert_ne!(
        ready.token.unwrap(),
        fs::read_to_string(data.join("first-token")).unwrap()
    );
    assert_ne!(
        fs::read_to_string(data.join("first-id")).unwrap(),
        fs::read_to_string(data.join("second-id")).unwrap()
    );
    manager.shutdown();
    assert_eq!(fs::read_dir(data.join("run")).unwrap().count(), 0);
}

#[test]
fn invalid_handshake_fails_and_cleans_its_own_waiting_process() {
    let body = format!("{READY}\nIFS= read -r line\n")
        .replace("\"protocol_version\":1", "\"protocol_version\":2");
    let (directory, manager) = fake_service(&body);
    manager.start(false).unwrap();
    let failed = wait_for(&manager, "failed");
    assert!(failed.token.is_none() && failed.error.unwrap().contains("does not match"));
    assert_eq!(
        fs::read_dir(directory.path().join("data/run"))
            .unwrap()
            .count(),
        0
    );
    manager.shutdown();
}

#[test]
fn quitting_during_startup_does_not_wait_for_handshake_timeout() {
    let (_directory, manager) = fake_service("IFS= read -r line\n");
    manager.start(false).unwrap();
    let started = Instant::now();
    manager.shutdown();
    manager.shutdown();
    assert!(started.elapsed() < Duration::from_secs(2));
    assert!(manager.snapshot().token.is_none());
    assert!(manager.snapshot().instance_id.is_none());
}

#[test]
fn startup_deadline_fails_without_publishing_unverified_connection() {
    let (directory, manager) = fake_service("IFS= read -r line\n");
    let instance = Instance {
        id: "synthetic-instance".into(),
        token: "synthetic-token".into(),
        ready_file: directory.path().join("absent-ready"),
        deadline: Instant::now(),
    };
    let (_sender, receiver) = mpsc::channel();
    let mut child = Command::new("/bin/sh")
        .args(["-c", "IFS= read -r line"])
        .stdin(Stdio::piped())
        .spawn()
        .unwrap();
    let result = manager.monitor(&mut child, &receiver, &instance);
    stop_child(&mut child, Duration::from_secs(1));
    assert!(matches!(result, Err(message) if message.contains("45 seconds")));
    assert!(manager.snapshot().token.is_none());
    assert!(manager.snapshot().instance_id.is_none());
}

#[test]
fn failed_service_requires_explicit_retry_and_does_not_inherit_secret_environment() {
    let body = "test -z \"$OPENBOT_FAKE_PARENT_SECRET\" || exit 8\nexit 7\n";
    let (directory, manager) = fake_service(body);
    std::env::set_var("OPENBOT_FAKE_PARENT_SECRET", "synthetic-secret");
    manager.start(false).unwrap();
    let failed = wait_for(&manager, "failed");
    assert!(failed.error.unwrap().contains('7'));
    assert_eq!(
        fs::read_dir(directory.path().join("data/run"))
            .unwrap()
            .count(),
        0
    );
    manager.start(true).unwrap();
    wait_for(&manager, "failed");
    manager.shutdown();
    std::env::remove_var("OPENBOT_FAKE_PARENT_SECRET");
}

#[test]
fn abnormal_python_exit_is_not_an_orderly_update_shutdown() {
    let mut child = Command::new("/bin/sh")
        .args(["-c", "IFS= read -r line; exit 1"])
        .stdin(Stdio::piped())
        .spawn()
        .unwrap();
    assert!(!stop_child(&mut child, Duration::from_secs(1)));
}
