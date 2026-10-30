use crate::service::Connection;
use reqwest::Url;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::io::Read;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

pub fn secure_endpoint(value: &str) -> Result<Url, String> {
    let url = Url::parse(value).map_err(|_| "Update endpoint is invalid".to_string())?;
    if url.scheme() != "https"
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
    {
        return Err("Update endpoint must be HTTPS without credentials or a fragment".into());
    }
    Ok(url)
}

pub fn gate_url(connection: &Connection, action: &str) -> Result<(Url, String), String> {
    if connection.status != "ready" || !matches!(action, "prepare" | "resume") {
        return Err("The owned Python service is not ready".into());
    }
    let base = connection
        .base_url
        .as_ref()
        .ok_or("Missing owned service address")?;
    let mut url = Url::parse(base).map_err(|_| "Invalid owned service address")?;
    if url.scheme() != "http"
        || url.host_str() != Some("127.0.0.1")
        || url.port().is_none()
        || url.port() == Some(0)
        || url.path() != "/"
        || url.query().is_some()
        || url.fragment().is_some()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err("Refusing an address outside the owned loopback instance".into());
    }
    let token = connection
        .token
        .clone()
        .filter(|v| !v.is_empty())
        .ok_or("Missing instance authentication")?;
    url.set_path(&format!("/api/desktop/update/{action}"));
    Ok((url, token))
}

pub fn bundle_root() -> Result<PathBuf, String> {
    std::env::current_exe()
        .map_err(|_| "Cannot locate running app".to_string())?
        .ancestors()
        .find(|p| p.extension().is_some_and(|e| e == "app"))
        .map(Path::to_path_buf)
        .ok_or("Updates require an installed .app bundle".into())
}

pub fn bundle_fingerprint(root: &Path) -> Result<BTreeMap<PathBuf, Vec<u8>>, String> {
    fn visit(
        root: &Path,
        path: &Path,
        result: &mut BTreeMap<PathBuf, Vec<u8>>,
    ) -> std::io::Result<()> {
        for entry in fs::read_dir(path)? {
            let path = entry?.path();
            let metadata = fs::symlink_metadata(&path)?;
            let key = path.strip_prefix(root).unwrap().to_path_buf();
            if metadata.is_symlink() {
                result.insert(
                    key,
                    format!(
                        "symlink:{}:{}",
                        metadata.permissions().mode(),
                        fs::read_link(&path)?.display()
                    )
                    .into_bytes(),
                );
            } else if metadata.is_dir() {
                result.insert(
                    key,
                    format!("directory:{}", metadata.permissions().mode()).into_bytes(),
                );
                visit(root, &path, result)?;
            } else if metadata.is_file() {
                let mut digest = Sha256::new();
                digest.update(metadata.permissions().mode().to_le_bytes());
                let mut input = fs::File::open(&path)?;
                let mut buffer = [0_u8; 65536];
                loop {
                    let length = input.read(&mut buffer)?;
                    if length == 0 {
                        break;
                    }
                    digest.update(&buffer[..length]);
                }
                result.insert(key, digest.finalize().to_vec());
            } else {
                return Err(std::io::Error::other("Unsupported bundle file"));
            }
        }
        Ok(())
    }
    let mut result = BTreeMap::new();
    result.insert(
        PathBuf::from("."),
        fs::metadata(root)
            .map_err(|_| "Cannot read app permissions")?
            .permissions()
            .mode()
            .to_le_bytes()
            .to_vec(),
    );
    visit(root, root, &mut result)
        .map_err(|_| "Cannot verify the installed application bundle".to_string())?;
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn release_endpoint_requires_https() {
        for bad in [
            "http://example.test/update",
            "file:///tmp/update",
            "https://user:secret@example.test/x",
            "https://example.test/x#key",
        ] {
            assert!(secure_endpoint(bad).is_err());
        }
        assert!(secure_endpoint("https://example.test/{{target}}/{{current_version}}").is_ok());
    }
    #[test]
    fn update_gate_never_accepts_arbitrary_urls_or_paths() {
        let mut connection = Connection {
            status: "ready",
            base_url: Some("http://127.0.0.1:12345".into()),
            token: Some("synthetic".into()),
            instance_id: Some("instance".into()),
            error: None,
        };
        assert_eq!(
            gate_url(&connection, "prepare").unwrap().0.path(),
            "/api/desktop/update/prepare"
        );
        for bad in [
            "http://localhost:12345",
            "http://127.0.0.1:12345/other",
            "http://evil.test:12345",
            "https://127.0.0.1:12345",
            "http://127.0.0.1:12345?token=x",
        ] {
            connection.base_url = Some(bad.into());
            assert!(gate_url(&connection, "prepare").is_err());
        }
        assert!(gate_url(&connection, "../arbitrary").is_err());
    }
    #[test]
    fn recovery_requires_every_bundle_file_and_link_to_match() {
        let temp = tempfile::tempdir().unwrap();
        fs::write(temp.path().join("python"), b"original").unwrap();
        std::os::unix::fs::symlink("python", temp.path().join("python3")).unwrap();
        let original = bundle_fingerprint(temp.path()).unwrap();
        fs::write(temp.path().join("python"), b"changed").unwrap();
        assert_ne!(bundle_fingerprint(temp.path()).unwrap(), original);
        fs::write(temp.path().join("python"), b"original").unwrap();
        assert_eq!(bundle_fingerprint(temp.path()).unwrap(), original);
        fs::set_permissions(
            temp.path().join("python"),
            fs::Permissions::from_mode(0o700),
        )
        .unwrap();
        assert_ne!(bundle_fingerprint(temp.path()).unwrap(), original);
        fs::remove_file(temp.path().join("python3")).unwrap();
        std::os::unix::fs::symlink("outside", temp.path().join("python3")).unwrap();
        assert_ne!(bundle_fingerprint(temp.path()).unwrap(), original);
    }
}
