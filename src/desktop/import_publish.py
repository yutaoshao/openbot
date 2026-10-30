"""Publish a staged offline import before the application opens its database."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from src.desktop.settings import DesktopSettings, write_private_json

IMPORT_DIRECTORY = "import-pending"


def apply_pending_import(settings: DesktopSettings) -> bool:
    """Move only owned paths, preserving a rollback copy until all moves succeed.

    The journal lives outside replaced paths. Every rename is recoverable after a
    crash: restore targets from backups on the next start, then report failure.
    """
    root = settings.data_dir
    pending = root / IMPORT_DIRECTORY
    journal = root / "import-journal.json"
    if journal.exists():
        recover_import(root, journal)
        raise RuntimeError("上次导入未完成，原应用数据已恢复。请重新预览并导入。")
    marker = pending / "ready.json"
    if not marker.exists():
        return False
    manifest = json.loads(marker.read_text(encoding="utf-8"))
    if manifest != {"version": 1, "paths": ["data", "config.yaml", "desktop-state.json"]}:
        raise RuntimeError("导入清单无效，未修改现有数据。")
    backup = root / ("import-backup-" + str(pending.stat().st_mtime_ns))
    backup.mkdir(mode=0o700)
    existed = {name: (root / name).exists() for name in manifest["paths"]}
    completed: list[str] = []
    write_private_json(journal, {"backup": backup.name, "started": completed, "existed": existed})
    try:
        for name in manifest["paths"]:
            staged = pending / name
            if staged.is_symlink() or not staged.exists():
                raise RuntimeError("导入暂存数据缺失。")
            # Journal intent before the first rename so interruption remains recoverable.
            completed.append(name)
            write_private_json(
                journal, {"backup": backup.name, "started": completed, "existed": existed}
            )
            target = root / name
            if target.exists():
                target.rename(backup / name)
            staged.rename(target)
        write_private_json(
            root / "import-result.json", {"status": "imported", "backup": backup.name}
        )
        marker.rename(backup / "import-manifest.json")
        journal.unlink()
        return True
    except BaseException:
        recover_import(root, journal)
        raise


def recover_import(root: Path, journal: Path) -> None:
    value = json.loads(journal.read_text(encoding="utf-8"))
    backup_name = value["backup"]
    if (
        not isinstance(backup_name, str)
        or not backup_name.startswith("import-backup-")
        or "/" in backup_name
    ):
        raise RuntimeError("导入恢复日志无效。")
    backup = root / backup_name
    for name in reversed(value["started"]):
        if name not in {"data", "config.yaml", "desktop-state.json"}:
            raise RuntimeError("导入恢复路径无效。")
        old = backup / name
        current = root / name
        staged = root / IMPORT_DIRECTORY / name
        if old.exists():
            if current.exists():
                current.rename(backup / (name + ".unpublished"))
            old.rename(current)
        elif not value["existed"][name] and not staged.exists() and current.exists():
            current.rename(backup / (name + ".unpublished"))
    write_private_json(
        root / "import-result.json", {"status": "failed_restored", "backup": backup.name}
    )
    # Keep the recovery intent until the replay trigger has been archived. A
    # crash before/after this rename must still enter recovery on the next start.
    marker = root / IMPORT_DIRECTORY / "ready.json"
    if marker.exists():
        marker.rename(backup / "failed-manifest.json")
    journal.unlink()
