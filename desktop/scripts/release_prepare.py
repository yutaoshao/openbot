"""Generate a release overlay and explicit build plan without signing or publishing."""

from __future__ import annotations

import argparse
import base64
import json
import re
import shlex
import tomllib
from pathlib import Path
from urllib.parse import urlsplit


def validate_endpoint(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.fragment
        or url.query
    ):
        raise ValueError("更新地址必须是无凭据、查询参数或片段的 HTTPS 地址。")
    return value


def validate_public_key(value: str) -> str:
    try:
        lines = base64.b64decode(value.strip(), validate=True).decode("utf-8").splitlines()
        raw = base64.b64decode(lines[-1], validate=True)
        if len(lines) != 2 or not lines[0].startswith("untrusted comment:") or len(raw) != 42:
            raise ValueError
        if raw[:2] not in {b"Ed", b"ED"}:
            raise ValueError
    except (ValueError, IndexError, UnicodeError) as exc:
        raise ValueError(
            "请提供 Tauri signer generate 生成的公开 .pub 内容，不要提供私钥。"
        ) from exc
    return value.strip()


def prepare_release(
    root: Path, endpoint: str, public_key: str, identity: str, minimum_macos: str
) -> dict:
    """Keep versions explicit and equal; this preparation never modifies source versions."""
    endpoint = validate_endpoint(endpoint)
    public_key = validate_public_key(public_key)
    if not identity.startswith("Developer ID Application:"):
        raise ValueError("发行需要显式提供 Developer ID Application 签名身份。")
    if not re.fullmatch(r"\d{2}\.\d+(?:\.\d+)?", minimum_macos):
        raise ValueError("请显式提供已验收的最低 macOS 版本。")
    config = json.loads((root / "desktop/src-tauri/tauri.conf.json").read_text())
    frontend = json.loads((root / "frontend/package.json").read_text())
    desktop = json.loads((root / "desktop/package.json").read_text())
    rust = tomllib.loads((root / "desktop/src-tauri/Cargo.toml").read_text())
    python = tomllib.loads((root / "pyproject.toml").read_text())
    versions = {
        config["version"],
        frontend["version"],
        desktop["version"],
        rust["package"]["version"],
        python["project"]["version"],
    }
    if len(versions) != 1:
        raise ValueError("应用壳、前端与桌面工程的发行版本不一致。")
    overlay = {
        "version": config["version"],
        "bundle": {
            "targets": ["app", "dmg"],
            "createUpdaterArtifacts": True,
            "macOS": {
                "signingIdentity": identity,
                "hardenedRuntime": True,
                "minimumSystemVersion": minimum_macos,
            },
        },
        "plugins": {
            "updater": {
                "endpoints": [endpoint],
                "pubkey": public_key,
                "requireSignedVersion": True,
                "allowDowngrades": False,
            }
        },
    }
    return {
        "version": config["version"],
        "target": "aarch64-apple-darwin",
        "overlay": overlay,
        "compile_environment": {
            "OPENBOT_UPDATE_ENDPOINT": endpoint,
            "OPENBOT_UPDATE_PUBLIC_KEY": public_key,
        },
        "required_secret_environment": [
            "TAURI_SIGNING_PRIVATE_KEY",
            "APPLE_API_ISSUER",
            "APPLE_API_KEY",
            "APPLE_API_KEY_PATH",
        ],
        "verification": [
            "codesign --verify --deep --strict --verbose=2 OpenBot.app",
            "xcrun stapler validate OpenBot.app",
            "spctl --assess --type execute --verbose=2 OpenBot.app",
            "xcrun stapler validate OpenBot.dmg",
        ],
        "status": "prepared_only_not_built_signed_notarized_or_published",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--public-key-file", type=Path, required=True)
    parser.add_argument("--signing-identity", required=True)
    parser.add_argument("--minimum-macos", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare_release(
            args.root,
            args.endpoint,
            args.public_key_file.read_text(),
            args.signing_identity,
            args.minimum_macos,
        )
        args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        overlay = args.output / "release.tauri.json"
        overlay.write_text(json.dumps(result["overlay"], indent=2) + "\n")
        result["build_command"] = shlex.join(
            [
                "env",
                *[f"{key}={value}" for key, value in result["compile_environment"].items()],
                "npm",
                "run",
                "tauri",
                "--",
                "build",
                "--target",
                result["target"],
                "--config",
                str(overlay.resolve()),
                "--",
                "--locked",
                "--offline",
            ]
        )
        (args.output / "release-plan.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            json.dumps({"status": result["status"], "plan": str(args.output / "release-plan.json")})
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
