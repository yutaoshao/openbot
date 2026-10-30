"""Synthetic smoke safety boundaries, without touching real user state."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

GUARD_PATH = Path(__file__).parents[2] / "desktop/probe/service_guard.py"
spec = importlib.util.spec_from_file_location("service_guard", GUARD_PATH)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_dotenv_disable_flag_required(monkeypatch):
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    with pytest.raises(RuntimeError, match="before core imports"):
        guard.verify_dotenv_disabled()


def test_real_dotenv_disable_skips_search(monkeypatch):
    import dotenv.main

    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")

    def unexpected_search(*_args, **_kwargs):
        raise AssertionError("dotenv search must not occur")

    monkeypatch.setattr(dotenv.main, "find_dotenv", unexpected_search)
    assert guard.verify_dotenv_disabled()


def test_unsupported_dotenv_disable_fails_closed(monkeypatch):
    import dotenv.main

    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setattr(dotenv.main, "load_dotenv", lambda: True)
    with pytest.raises(RuntimeError, match="did not honor"):
        guard.verify_dotenv_disabled()


@pytest.mark.parametrize("filename", [".env", "config.yaml"])
def test_reads_of_host_configuration_are_rejected(tmp_path, filename):
    with pytest.raises(PermissionError):
        guard.audit_synthetic_io(tmp_path / "workspace", "open", (str(tmp_path / filename),))


@pytest.mark.parametrize("event", ["socket.connect", "socket.bind", "socket.sendto"])
def test_non_loopback_network_is_rejected(tmp_path, event):
    with pytest.raises(PermissionError, match="loopback"):
        guard.audit_synthetic_io(tmp_path, event, (None, ("192.0.2.1", 443)))


def test_synthetic_config_and_loopback_network_are_allowed(tmp_path):
    guard.audit_synthetic_io(tmp_path, "open", (str(tmp_path / "config.yaml"),))
    guard.audit_synthetic_io(tmp_path, "socket.connect", (None, ("127.0.0.1", 12345)))


@pytest.mark.parametrize("host", ["example.invalid", b"example.invalid", "localhost", None])
def test_dns_targets_must_be_literal_loopback(tmp_path, host):
    with pytest.raises(PermissionError, match="literal loopback"):
        guard.audit_synthetic_io(tmp_path, "socket.getaddrinfo", (host, 443, 0, 0, 0))


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", b"127.0.0.1", b"::1"])
def test_literal_loopback_dns_and_datagrams_are_allowed(tmp_path, host):
    guard.audit_synthetic_io(tmp_path, "socket.getaddrinfo", (host, 12345, 0, 0, 0))
    guard.audit_synthetic_io(tmp_path, "socket.sendto", (None, (host, 12345)))


@pytest.mark.parametrize(
    "line",
    [
        "2026-10-29 [error    ] failed",
        "[critical ] failure",
        "ERROR: ASGI error",
        "CRITICAL: shutting down",
        "Traceback (most recent call last):",
        "planner.parse_failed",
    ],
)
def test_error_log_formats_fail_an_otherwise_successful_worker(line):
    original = {"status": "passed"}
    result = guard.evaluate_worker_report(original, line, 0)
    assert result["status"] == "failed"
    assert result["unexpected_error_logs"] == 1
    assert original == {"status": "passed"}


def test_error_line_count_and_nonzero_exit_are_preserved():
    report = guard.evaluate_worker_report({"status": "passed"}, "ERROR: one\nCRITICAL: two", 1)
    assert report["status"] == "failed"
    assert report["unexpected_error_logs"] == 2


def test_normal_error_event_subscription_is_not_an_error_log():
    report = guard.evaluate_worker_report(
        {"status": "passed"},
        "[debug] subscribed pattern=app.agent_error\nINFO: ready",
        0,
    )
    assert report["status"] == "passed"
    assert report["unexpected_error_logs"] == 0
