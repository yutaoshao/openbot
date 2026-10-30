"""Behavioral checks for the offline desktop probe."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROBE_PATH = Path(__file__).parents[2] / "desktop/probe/runtime_probe.py"
spec = importlib.util.spec_from_file_location("desktop_runtime_probe", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_failed_check_is_reported_without_false_success():
    def failing():
        raise RuntimeError("missing bundled resource")

    assert probe.check_result("resource", failing) == {
        "name": "resource",
        "status": "failed",
        "error": "missing bundled resource",
    }


def test_explicit_python_child_works_without_development_path(tmp_path):
    assert probe.check_child(tmp_path) == {
        "major": 3,
        "minor": sys.version_info.minor,
        "result": 42,
    }


def test_native_tokenizer_does_not_claim_production_resources():
    assert probe.check_tokenizer() == {
        "native_roundtrip": True,
        "production_encoding_resources": "not_verified",
    }


def test_missing_source_root_rejected_before_configuration_load(tmp_path):
    with pytest.raises(ValueError, match="Source root"):
        probe.run_probe(tmp_path, None)


def test_ripgrep_uses_explicit_binary_and_searches_synthetic_data(tmp_path):
    rg = probe.shutil.which("rg")
    if rg is None:
        pytest.skip("rg not available on test host")
    assert probe.check_search(Path(rg), tmp_path)["search"] is True


async def test_wrong_executor_interpreter_is_not_accepted(monkeypatch):
    from types import SimpleNamespace

    from src.tools.builtin.code_executor import CodeExecutorTool

    async def execute(_self, _args):
        return SimpleNamespace(
            is_error=False,
            content=json.dumps({"version": [3, 9], "executable": "/usr/bin/python3"})
            + "\n\nStderr:\nsynthetic system warning",
        )

    monkeypatch.setattr(CodeExecutorTool, "execute", execute)
    with pytest.raises(RuntimeError, match="different interpreter"):
        await probe.check_existing_executor_async()


async def test_matching_version_from_wrong_python_path_is_not_accepted(monkeypatch):
    from types import SimpleNamespace

    from src.tools.builtin.code_executor import CodeExecutorTool

    async def execute(_self, _args):
        return SimpleNamespace(
            is_error=False,
            content=json.dumps(
                {
                    "version": list(sys.version_info[:2]),
                    "executable": "/different/python3",
                }
            ),
        )

    monkeypatch.setattr(CodeExecutorTool, "execute", execute)
    with pytest.raises(RuntimeError, match="runtime executable"):
        await probe.check_existing_executor_async()


def test_missing_production_cache_is_rejected_without_downloading(tmp_path, monkeypatch):
    import tiktoken

    def unexpected_network(*_args, **_kwargs):
        raise AssertionError("Probe must not download tokenizer resources")

    monkeypatch.setattr(tiktoken, "get_encoding", unexpected_network)
    with pytest.raises(RuntimeError, match="Missing or invalid production tokenizer"):
        probe.check_production_tokenizers(tmp_path)


@pytest.mark.parametrize("enabled,on_path", [(True, False), (False, True)])
async def test_executor_host_user_site_is_rejected(monkeypatch, enabled, on_path):
    from types import SimpleNamespace

    from src.tools.builtin.code_executor import CodeExecutorTool

    async def execute(_self, _args):
        return SimpleNamespace(
            is_error=False,
            content=json.dumps(
                {
                    "version": list(sys.version_info[:2]),
                    "executable": sys.executable,
                    "user_site_enabled": enabled,
                    "user_site_on_path": on_path,
                }
            ),
        )

    monkeypatch.setattr(CodeExecutorTool, "execute", execute)
    with pytest.raises(RuntimeError, match="host user-site"):
        await probe.check_existing_executor_async()
