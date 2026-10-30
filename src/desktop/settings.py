"""Private, atomic desktop settings independent of the chosen workspace."""

from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.application.settings import SecretValue, SettingsService
from src.core.config import AppConfig

MODEL_KEY_ENV = "OPENBOT_DESKTOP_MODEL_KEY"
EXECUTION_TOOLS = ("bash", "code_executor")


def is_local_endpoint(url: str) -> bool:
    host = urlsplit(url).hostname
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


class DesktopModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai_compatible", "openai_responses", "anthropic"] = "openai_compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = Field(default="", max_length=256)
    api_key: str = Field(default="", max_length=8192, repr=False)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("模型地址须为不含密钥、查询参数或片段的 HTTP(S) 地址。")
        return value.strip().rstrip("/")


class DesktopState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    configured: bool = False
    work_dir: str
    model: DesktopModel = Field(default_factory=DesktopModel)
    permissions: dict[Literal["bash", "code_executor"], bool] = Field(
        default_factory=lambda: {name: False for name in EXECUTION_TOOLS}
    )
    tool_enabled: dict[str, bool] = Field(default_factory=dict)
    services: dict = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict, repr=False)


def write_private_json(path: Path, value: dict) -> None:
    write_private_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_private_text(path: Path, value: str) -> None:
    """Publish one complete document with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as fh:
            temporary = Path(fh.name)
            os.fchmod(fh.fileno(), 0o600)
            fh.write(value)
            fh.flush()
            os.fsync(fh.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class DesktopSettings:
    """Own desktop model credentials, permissions and workspace as one transaction."""

    def __init__(self, data_dir: Path) -> None:
        if not data_dir.is_absolute():
            raise ValueError("Desktop data directory must be absolute.")
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_dir.chmod(0o700)
        self.path = self.data_dir / "desktop-state.json"
        if not self.path.exists():
            workspace = self.data_dir / "workspace"
            workspace.mkdir(exist_ok=True)
            self.save(DesktopState(work_dir=str(workspace)))

    def read(self) -> DesktopState:
        return DesktopState.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, state: DesktopState) -> None:
        write_private_json(self.path, state.model_dump())

    def prepare_setup(self, model: dict, work_dir: str) -> DesktopState:
        previous = self.read()
        options = dict(model)
        if options.get("provider") == "openai":
            options["provider"] = "openai_compatible"
        if not options.get("api_key"):
            options["api_key"] = previous.model.api_key
        selected = DesktopModel.model_validate(options)
        if not selected.model.strip():
            raise ValueError("请填写模型名称。")
        if not selected.api_key and not is_local_endpoint(selected.base_url):
            raise ValueError("首次配置远程模型服务时需要填写 API Key。")
        if selected.provider == "openai_responses" and not selected.base_url.endswith("/v1"):
            raise ValueError("OpenAI Responses 服务地址须以 /v1 结尾。")
        workspace = Path(work_dir).expanduser()
        if not workspace.is_absolute() or not workspace.is_dir():
            raise ValueError("请选择已存在的绝对路径工作目录。")
        return previous.model_copy(
            update={"configured": True, "model": selected, "work_dir": str(workspace.resolve())}
        )

    def prepare_config(self, config: AppConfig, port: int, runtime: Path) -> AppConfig:
        state = self.read()
        values = config.model_dump()
        values.update(state.services)
        if state.services:
            values["telegram"]["webhook_secret"] = state.secrets.get("telegram.webhook_secret")
        values["model"]["primary"].update(
            provider=state.model.provider,
            model=state.model.model or "not-configured",
            base_url=state.model.base_url,
            api_key_env=MODEL_KEY_ENV,
        )
        values["storage"]["db_path"] = str(self.data_dir / "data" / "openbot.db")
        values["wechat"]["state_path"] = str(self.data_dir / "data" / "wechat" / "ilink_state.json")
        values["log"]["file"] = str(self.data_dir / "data" / "logs" / "openbot.log")
        values["api"].update(
            enabled=True,
            host="127.0.0.1",
            port=port,
            local_only=True,
            serve_frontend=True,
            frontend_dist=str(runtime.parent / "frontend"),
            cors_origins=[
                "tauri://localhost",
                "http://tauri.localhost",
                "https://tauri.localhost",
                "http://127.0.0.1:5173",
                f"http://127.0.0.1:{port}",
            ],
        )
        if not state.configured:
            for name in ("telegram", "feishu", "wechat", "embedding", "reranker"):
                values[name]["enabled"] = False
        return AppConfig.model_validate(values)

    def install_model_key(self) -> None:
        state = self.read()
        # SDK construction requires a nonempty key even before onboarding/local no-key services.
        os.environ[MODEL_KEY_ENV] = state.model.api_key or "openbot-local-no-key"
        from src.desktop.services import SECRET_ENVS

        for key, env in SECRET_ENVS.items():
            if key != "model.primary":
                os.environ[env] = state.secrets.get(key, "")


class DesktopSettingsService(SettingsService):
    """Desktop management can inspect presence, never reveal stored credential values."""

    def __init__(self, config_path: str, desktop_settings: DesktopSettings) -> None:
        super().__init__(config_path)
        self._desktop_settings = desktop_settings

    def snapshot(self, config: AppConfig) -> dict:
        values = config.model_dump()
        values["telegram"]["webhook_secret"] = None
        return values

    def read_secret_values(self, config: AppConfig) -> list[SecretValue]:
        return [
            SecretValue(
                item.env_name,
                "",
                bool(self._desktop_settings.read().model.api_key)
                if item.env_name == MODEL_KEY_ENV
                else item.is_set,
            )
            for item in super().read_secret_values(config)
        ]
