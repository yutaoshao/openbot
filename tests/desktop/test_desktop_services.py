from __future__ import annotations

import copy
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.agent.coordination import UserExecutionCoordinator
from src.api import create_api_app
from src.application.runtime import RuntimeEnvironment
from src.core.config import AppConfig
from src.desktop.service import DesktopService
from src.desktop.services import (
    SECRET_ENVS,
    configuration,
    imported_service_state,
    prepare_services,
)
from src.desktop.settings import DesktopSettings
from src.tools.builtin import BashTool, CodeExecutorTool
from src.tools.registry import ToolRegistry


def fixture(tmp_path):
    settings = DesktopSettings(tmp_path / "app")
    state = settings.prepare_setup(
        {"model": "synthetic", "base_url": "http://127.0.0.1:1/v1"}, settings.read().work_dir
    )
    settings.save(state)
    config = AppConfig(telegram={"enabled": False})
    return settings, config


def test_services_save_keeps_credentials_private_and_preserves_blank(tmp_path):
    settings, config = fixture(tmp_path)
    values = configuration(settings, config)
    values["telegram"]["enabled"] = True
    original = copy.deepcopy(values)
    state = prepare_services(
        settings,
        config,
        {"configuration": values, "secrets": {"telegram.bot_token": "synthetic-token"}},
    )
    assert values == original
    settings.save(state)
    assert settings.path.stat().st_mode & 0o777 == 0o600
    assert "synthetic-token" not in str(configuration(settings, config))
    state = prepare_services(
        settings, config, {"configuration": values, "secrets": {"telegram.bot_token": ""}}
    )
    assert state.secrets["telegram.bot_token"] == "synthetic-token"
    with pytest.raises(ValueError):
        prepare_services(
            settings, config, {"configuration": values, "clear_secrets": ["telegram.bot_token"]}
        )


def test_env_binding_is_owned_and_local_models_can_have_no_key(tmp_path, monkeypatch):
    settings, config = fixture(tmp_path)
    values = configuration(settings, config)
    values["model"]["fallback"] = {**values["model"]["primary"], "api_key_env": ""}
    values["model"]["primary"]["api_key_env"] = "UNTRUSTED_ENV"
    state = prepare_services(settings, config, {"configuration": values})
    settings.save(state)
    for env in SECRET_ENVS.values():
        monkeypatch.setenv(env, "")
    monkeypatch.setenv("TAVILY_API_KEY", "parent-secret")
    settings.install_model_key()
    assert os.environ["TAVILY_API_KEY"] == ""
    assert state.services["model"]["fallback"]["api_key_env"] == "OPENBOT_DESKTOP_FALLBACK_KEY"
    runtime = settings.prepare_config(config, 1234, tmp_path / "runtime")
    assert runtime.model.fallback.api_key_env == "OPENBOT_DESKTOP_FALLBACK_KEY"


def test_import_uses_explicit_env_and_pauses_all_channels(tmp_path):
    settings, _ = fixture(tmp_path)
    config = AppConfig(telegram={"enabled": True, "webhook_secret": "synthetic-hook"})
    state = imported_service_state(
        config,
        {
            "ANTHROPIC_API_KEY": "synthetic-model",
            "TELEGRAM_BOT_TOKEN": "synthetic-token",
            "HOME": "ignored",
        },
        settings.read(),
    )
    assert state.model.api_key == "synthetic-model"
    assert state.secrets["telegram.webhook_secret"] == "synthetic-hook"
    assert all(not state.services[name]["enabled"] for name in ("telegram", "feishu", "wechat"))
    assert state.services["telegram"]["webhook_secret"] is None
    assert "HOME" not in state.secrets


async def test_service_api_rejects_busy_and_never_echoes_invalid_credentials(tmp_path):
    settings, config = fixture(tmp_path)
    registry = ToolRegistry()
    registry.register(BashTool(root=tmp_path))
    registry.register(CodeExecutorTool(root=tmp_path))
    service = DesktopService(settings, token="synthetic-token-32-characters-long", runtime=tmp_path)
    app = SimpleNamespace(
        config_path=str(settings.data_dir / "config.yaml"),
        runtime=RuntimeEnvironment(configure_api=service.install_api),
        execution_coordinator=UserExecutionCoordinator(),
        tool_registry=registry,
        request_restart=AsyncMock(),
    )
    api = create_api_app(config=config, application=app, tool_registry=registry)
    api.state.chat_runs = SimpleNamespace(busy=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api),
        base_url="http://127.0.0.1",
        headers={"Authorization": "Bearer synthetic-token-32-characters-long"},
    ) as client:
        snapshot = (await client.get("/api/desktop/services")).json()
        response = await client.put(
            "/api/desktop/services", json={"configuration": snapshot["configuration"]}
        )
        assert response.status_code == 409
        app.request_restart.assert_not_awaited()
        snapshot["configuration"]["model"]["primary"]["provider"] = (
            "synthetic-secret-in-invalid-provider"
        )
        response = await client.put(
            "/api/desktop/services", json={"configuration": snapshot["configuration"]}
        )
        assert response.status_code == 422
        assert "synthetic-secret" not in response.text
        assert (await client.put("/api/settings", json={})).status_code == 409
        api.state.chat_runs.busy = False
        snapshot["configuration"] = configuration(settings, config)
        response = await client.put(
            "/api/desktop/services", json={"configuration": snapshot["configuration"]}
        )
        assert response.status_code == 200
        assert not app.execution_coordinator.accepting
        app.request_restart.assert_awaited_once()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("model", "routing", "tiers"), []),
        (("model", "routing", "tiers"), None),
        (("model", "routing"), None),
        (("model", "primary"), []),
        (("model", "routing", "tiers", "simple"), None),
        (("model", "routing", "rules"), []),
        (("model", "max_retries"), -1),
        (("model", "max_retries"), 11),
        (("model", "retry_base_delay"), 0),
        (("model", "primary", "max_tokens"), 0),
        (("model", "primary", "max_tokens"), True),
        (("model", "primary", "context_window"), 100),
        (("model", "primary", "temperature"), 2.1),
        (("model", "primary", "pricing_input"), -1),
        (("model", "primary", "connect_timeout"), 0),
        (("model", "primary", "read_timeout"), -1),
        (("model", "routing", "enabled"), "false"),
        (("model", "routing", "rules", "simple_max_chars"), 700),
        (("model", "routing", "rules", "tool_count_complex_threshold"), 0),
        (("telegram", "enabled"), 0),
        (("telegram", "enable_streaming"), "false"),
        (("telegram", "stream_throttle"), 0),
        (("telegram", "allowed_user_ids"), [True]),
        (("telegram", "allowed_user_ids"), [-1]),
        (("telegram", "allowed_user_ids"), ["123"]),
        (("embedding", "dimensions"), 0),
        (("reranker", "top_n"), -1),
        (("wechat", "poll_interval"), 0),
        (("wechat", "max_backoff"), 1),
    ],
)
async def test_invalid_service_boundary_is_422_and_preserves_state(tmp_path, path, value):
    settings, config = fixture(tmp_path)
    previous = settings.path.read_bytes()
    registry = ToolRegistry()
    registry.register(BashTool(root=tmp_path))
    registry.register(CodeExecutorTool(root=tmp_path))
    service = DesktopService(settings, token="synthetic-token-32-characters-long", runtime=tmp_path)
    app = SimpleNamespace(
        config_path=str(settings.data_dir / "config.yaml"),
        runtime=RuntimeEnvironment(configure_api=service.install_api),
        execution_coordinator=UserExecutionCoordinator(),
        tool_registry=registry,
        request_restart=AsyncMock(),
    )
    api = create_api_app(config=config, application=app, tool_registry=registry)
    api.state.chat_runs = SimpleNamespace(busy=False)
    selected = configuration(settings, config)
    parent = selected
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api),
        base_url="http://127.0.0.1",
        headers={"Authorization": "Bearer synthetic-token-32-characters-long"},
    ) as client:
        response = await client.put(
            "/api/desktop/services",
            json={
                "configuration": selected,
                "secrets": {"telegram.bot_token": "never-echo-synthetic-secret"},
            },
        )
    assert response.status_code == 422
    assert "never-echo-synthetic-secret" not in response.text
    assert settings.path.read_bytes() == previous
    assert app.execution_coordinator.accepting
    app.request_restart.assert_not_awaited()


def test_frontend_endpoint_defaults_bind_empty_env_before_responses_validation(tmp_path):
    settings, config = fixture(tmp_path)
    values = configuration(settings, config)
    endpoint = {
        "provider": "openai_responses",
        "model": "synthetic-model",
        "base_url": "https://example.test/v1",
        "max_tokens": 4096,
        "context_window": None,
        "temperature": 0.7,
        "api_key_env": "",
        "pricing_input": None,
        "pricing_output": None,
        "connect_timeout": 30,
        "read_timeout": 300,
        "reasoning_effort": "medium",
        "verbosity": "low",
    }
    values["model"]["fallback"] = endpoint.copy()
    values["model"]["routing"].update(
        enabled=True, tiers={"simple": endpoint.copy(), "complex": endpoint.copy()}
    )
    selected = prepare_services(
        settings,
        config,
        {
            "configuration": values,
            "secrets": {
                "model.fallback": "synthetic-fallback",
                "model.routing.simple": "synthetic-simple",
                "model.routing.complex": "synthetic-complex",
            },
        },
    )
    assert selected.services["model"]["fallback"]["api_key_env"] == SECRET_ENVS["model.fallback"]
    assert (
        selected.services["model"]["routing"]["tiers"]["simple"]["api_key_env"]
        == SECRET_ENVS["model.routing.simple"]
    )


def test_disabled_routing_keeps_incomplete_drafts_but_still_validates_values(tmp_path):
    settings, config = fixture(tmp_path)
    values = configuration(settings, config)
    endpoint = {
        **values["model"]["primary"],
        "model": "",
        "base_url": "https://example.test/v1",
        "api_key_env": "",
    }
    values["model"]["routing"].update(
        enabled=False, tiers={"simple": endpoint.copy(), "complex": endpoint.copy()}
    )
    result = prepare_services(settings, config, {"configuration": values})
    assert not result.services["model"]["routing"]["enabled"]
    assert result.services["model"]["routing"]["tiers"]["simple"]["model"] == ""
    assert not result.secrets.get("model.routing.simple")
    values["model"]["routing"]["enabled"] = True
    with pytest.raises(ValueError):
        prepare_services(settings, config, {"configuration": values})
    values["model"]["routing"]["enabled"] = False
    values["model"]["routing"]["tiers"]["simple"]["base_url"] = (
        "https://user:private@example.test/v1"
    )
    with pytest.raises(ValueError):
        prepare_services(settings, config, {"configuration": values})
    values["model"]["routing"]["tiers"]["simple"]["base_url"] = None
    values["model"]["routing"]["tiers"]["simple"]["max_tokens"] = 0
    with pytest.raises(ValueError):
        prepare_services(settings, config, {"configuration": values})
