"""Persistent state helpers for the WeChat iLink adapter."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class WeChatLoginState:
    """Single-account login state persisted on disk."""

    account_id: str
    bot_token: str
    api_base_url: str
    get_updates_buf: str = ""
    user_id: str = ""
    last_login_at: str = ""

    @property
    def is_valid(self) -> bool:
        return bool(self.account_id and self.bot_token and self.api_base_url)


class WeChatStateStore:
    """Read and write the local iLink login state file."""

    def __init__(self, state_path: str) -> None:
        self._path = Path(state_path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> WeChatLoginState | None:
        """Return the current login state, or ``None`` when absent."""
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"WeChat state file is not valid JSON: {self._path}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"WeChat state file must contain a JSON object: {self._path}")
        state = WeChatLoginState(
            account_id=str(payload.get("account_id", "")).strip(),
            bot_token=str(payload.get("bot_token", "")).strip(),
            api_base_url=str(payload.get("api_base_url", "")).strip(),
            get_updates_buf=str(payload.get("get_updates_buf", "")),
            user_id=str(payload.get("user_id", "")).strip(),
            last_login_at=str(payload.get("last_login_at", "")).strip(),
        )
        return state if state.is_valid else None

    def save_login(
        self,
        *,
        account_id: str,
        bot_token: str,
        api_base_url: str,
        user_id: str = "",
    ) -> WeChatLoginState:
        """Persist a successful QR login."""
        state = WeChatLoginState(
            account_id=account_id.strip(),
            bot_token=bot_token.strip(),
            api_base_url=api_base_url.strip(),
            get_updates_buf="",
            user_id=user_id.strip(),
            last_login_at=datetime.now(UTC).isoformat(),
        )
        self._write(state)
        return state

    def update_get_updates_buf(self, get_updates_buf: str) -> WeChatLoginState | None:
        """Persist the latest long-poll cursor."""
        state = self.load()
        if state is None:
            return None
        state.get_updates_buf = get_updates_buf
        self._write(state)
        return state

    def update_api_base_url(self, api_base_url: str) -> WeChatLoginState | None:
        """Persist an updated polling base URL after an IDC redirect."""
        state = self.load()
        if state is None:
            return None
        state.api_base_url = api_base_url.strip()
        self._write(state)
        return state

    def login_png_path(self) -> Path:
        """Return the local QR image path that the CLI should generate."""
        return self._path.parent / "login.png"

    def _write(self, state: WeChatLoginState) -> None:
        if not state.is_valid:
            raise RuntimeError("Refusing to persist an invalid WeChat login state.")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        payload: dict[str, Any] = asdict(state)
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self._path)
        try:
            self._path.chmod(0o600)
        except OSError:
            return
