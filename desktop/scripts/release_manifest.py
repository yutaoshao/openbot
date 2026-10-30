"""Prepare updater metadata from existing signed artifacts; never upload it."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


def release_manifest(
    version: str, artifact: Path, signature: Path, public_url: str, notes: str
) -> dict:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError("发行版本必须是明确的语义版本号。")
    parsed = urlsplit(public_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("更新包地址必须为无凭据的 HTTPS 地址。")
    if not artifact.name.endswith(".app.tar.gz") or not artifact.is_file():
        raise ValueError("请选择实际构建的 .app.tar.gz 更新包。")
    encoded = signature.read_text().strip()
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise ValueError("更新包签名文件格式无效。") from exc
    # Metadata generation is not signature verification. Installation verifies it
    # with the compiled trust key; require the version-binding comment here too.
    comments = [
        line.removeprefix("trusted comment: ")
        for line in decoded.splitlines()
        if line.startswith("trusted comment: ")
    ]
    bound = [
        field.removeprefix("version:")
        for comment in comments
        for field in comment.split("\t")
        if field.startswith("version:")
    ]
    if bound != [version]:
        raise ValueError("签名未绑定目标版本；请用 Tauri signer sign --app-version 重新签名。")
    return {
        "version": version,
        "notes": notes,
        "platforms": {
            "darwin-aarch64": {"signature": encoded, "url": public_url},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--notes-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = release_manifest(
            args.version, args.artifact, args.signature, args.url, args.notes_file.read_text()
        )
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        with args.artifact.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        print(
            json.dumps(
                {
                    "manifest": str(args.output),
                    "sha256": digest,
                    "status": "local_metadata_only_not_signature_verified_or_published",
                }
            )
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
