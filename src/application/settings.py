"""Application-level settings persistence helpers."""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml
from ruamel.yaml import YAML

from src.core.config import AppConfig

_ROUND_TRIP_INDENT = {"mapping": 2, "sequence": 4, "offset": 2}


@dataclass(frozen=True)
class SettingsUpdateResult:
    """Result of applying a settings patch to ``config.yaml``."""

    config: AppConfig
    restart_required: bool
    restart_reasons: list[str]


class SettingsService:
    """Validate and persist editable runtime settings to ``config.yaml``."""

    def __init__(self, config_path: str) -> None:
        self._config_path = Path(config_path)
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.indent(**_ROUND_TRIP_INDENT)

    def snapshot(self, config: AppConfig) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the saved config."""
        return config.model_dump()

    def update_config(
        self,
        current_config: AppConfig,
        patch: dict[str, Any],
    ) -> SettingsUpdateResult:
        """Persist an editable settings patch and validate the result."""
        document = self._load_document(current_config)
        changed_sections = self._apply_patch(document, patch)
        if not changed_sections:
            return SettingsUpdateResult(
                config=current_config,
                restart_required=False,
                restart_reasons=[],
            )

        rendered = self._dump_document(document)
        validated_config = self._validate_rendered_config(rendered)
        self._write_atomic(rendered)
        return SettingsUpdateResult(
            config=validated_config,
            restart_required=True,
            restart_reasons=_restart_reasons(changed_sections),
        )

    def _load_document(self, current_config: AppConfig) -> Any:
        if self._config_path.exists():
            with self._config_path.open(encoding="utf-8") as fh:
                loaded = self._yaml.load(fh)
            if loaded is not None:
                return loaded
        return self._yaml.load(
            yaml.safe_dump(current_config.model_dump(), sort_keys=False),
        )

    def _dump_document(self, document: Any) -> str:
        buffer = StringIO()
        self._yaml.dump(document, buffer)
        return buffer.getvalue()

    def _validate_rendered_config(self, rendered: str) -> AppConfig:
        parsed = yaml.safe_load(rendered) or {}
        return AppConfig(**parsed)

    def _write_atomic(self, rendered: str) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._config_path.parent,
            delete=False,
            suffix=self._config_path.suffix,
        ) as fh:
            fh.write(rendered)
            tmp_path = Path(fh.name)
        tmp_path.replace(self._config_path)

    def _apply_patch(self, document: Any, patch: dict[str, Any]) -> set[str]:
        changed_sections: set[str] = set()
        for section, section_patch in patch.items():
            if not isinstance(section_patch, dict) or not section_patch:
                continue
            target = _ensure_mapping(document, section)
            for key, value in section_patch.items():
                if target.get(key) == value:
                    continue
                target[key] = value
                changed_sections.add(section)
        return changed_sections


def _ensure_mapping(document: Any, key: str) -> Any:
    current = document.get(key)
    if isinstance(current, dict):
        return current
    document[key] = {}
    return document[key]


def _restart_reasons(changed_sections: set[str]) -> list[str]:
    ordered_reasons = ["telegram", "model"]
    return [reason for reason in ordered_reasons if reason in changed_sections]
