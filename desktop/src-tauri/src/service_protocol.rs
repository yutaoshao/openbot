use serde::{Deserialize, Serialize};
use std::fs::{self, OpenOptions};
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::Path;

// The plugin focuses an existing window. This lease also fails closed if two
// plugin instances race while creating their notification socket.
pub struct InstanceLease(fs::File);

impl InstanceLease {
    pub fn acquire(data: &Path) -> Result<Self, String> {
        fs::create_dir_all(data).map_err(|error| error.to_string())?;
        fs::set_permissions(data, fs::Permissions::from_mode(0o700))
            .map_err(|error| error.to_string())?;
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(data.join("desktop-instance.lock"))
            .map_err(|error| error.to_string())?;
        file.set_permissions(fs::Permissions::from_mode(0o600))
            .map_err(|error| error.to_string())?;
        // SAFETY: flock only uses the valid descriptor and constant lock flags.
        if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return Err(
                "Another OpenBot instance already owns this application data directory".into(),
            );
        }
        Ok(Self(file))
    }
}

impl Drop for InstanceLease {
    fn drop(&mut self) {
        // SAFETY: the descriptor remains open until this guard is dropped.
        unsafe {
            libc::flock(self.0.as_raw_fd(), libc::LOCK_UN);
        }
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Connection {
    pub status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub base_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub instance_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub token: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl Connection {
    pub(super) fn starting() -> Self {
        Self {
            status: "starting",
            base_url: None,
            instance_id: None,
            token: None,
            error: None,
        }
    }

    pub(super) fn failed(error: String) -> Self {
        Self {
            status: "failed",
            error: Some(error),
            ..Self::starting()
        }
    }
}

pub fn web_console_url(connection: &Connection) -> Result<String, String> {
    let invalid = || "The local Web console is not ready for this desktop instance".to_string();
    if connection.status != "ready" {
        return Err(invalid());
    }
    let base = connection.base_url.as_deref().ok_or_else(invalid)?;
    let port_text = base.strip_prefix("http://127.0.0.1:").ok_or_else(invalid)?;
    let port: u16 = port_text.parse().map_err(|_| invalid())?;
    if port == 0 || port.to_string() != port_text {
        return Err(invalid());
    }
    let token = connection.token.as_deref().ok_or_else(invalid)?;
    let instance = connection.instance_id.as_deref().ok_or_else(invalid)?;
    let is_identity = |value: &str| {
        value.len() == 64
            && value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    };
    if !is_identity(token) || !is_identity(instance) {
        return Err(invalid());
    }
    Ok(format!("{base}/#openbot-desktop-token={token}"))
}

#[derive(Deserialize)]
struct ReadyFile {
    protocol_version: u32,
    instance_id: String,
    pid: u32,
    port: u16,
}

pub(super) fn verified_port(
    path: &Path,
    instance_id: &str,
    pid: u32,
) -> Result<Option<u16>, String> {
    let mut file = match OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
    {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(format!("Cannot inspect service handshake: {error}")),
    };
    let metadata = file.metadata().map_err(|error| error.to_string())?;
    if !metadata.file_type().is_file() || metadata.permissions().mode() & 0o777 != 0o600 {
        return Err("Service handshake must be a regular file with mode 0600".into());
    }
    if metadata.len() > 4096 {
        return Err("Service handshake exceeds its size limit".into());
    }
    let mut bytes = Vec::new();
    (&mut file)
        .take(4097)
        .read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    let ready: ReadyFile = serde_json::from_slice(&bytes)
        .map_err(|_| "Service handshake is not valid protocol JSON".to_string())?;
    if ready.protocol_version != 1
        || ready.instance_id != instance_id
        || ready.pid != pid
        || ready.port == 0
    {
        return Err("Service handshake does not match the launched process".into());
    }
    Ok(Some(ready.port))
}
