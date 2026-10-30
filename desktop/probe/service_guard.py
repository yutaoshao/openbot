"""Fail-closed guards for the external, synthetic service smoke process."""

from __future__ import annotations

import os
import re
from pathlib import Path

_LITERAL_LOOPBACKS = {"127.0.0.1", "::1", b"127.0.0.1", b"::1"}


def verify_dotenv_disabled() -> str:
    import importlib.metadata

    import dotenv.main

    if os.environ.get("PYTHON_DOTENV_DISABLED") != "1":
        raise RuntimeError("PYTHON_DOTENV_DISABLED=1 must be set before core imports")
    original = dotenv.main.find_dotenv

    def denied_search(*_args, **_kwargs):
        raise RuntimeError("dotenv ancestor search is forbidden in service smoke")

    dotenv.main.find_dotenv = denied_search
    try:
        if dotenv.main.load_dotenv() is not False:
            raise RuntimeError("Installed python-dotenv did not honor its disable flag")
    except BaseException:
        dotenv.main.find_dotenv = original
        raise
    # Keep the search guard installed for this disposable process.
    return importlib.metadata.version("python-dotenv")


def audit_synthetic_io(workspace: Path, event: str, args: tuple) -> None:
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = Path(os.fsdecode(args[0])).resolve()
        if path.name == ".env":
            raise PermissionError("Reading dotenv files is forbidden in service smoke")
        if path.name == "config.yaml" and not path.is_relative_to(workspace):
            raise PermissionError("Only synthetic config.yaml may be read")
    if event in {"socket.connect", "socket.bind", "socket.sendto"}:
        address = args[1]
        if isinstance(address, tuple) and address[0] not in _LITERAL_LOOPBACKS:
            raise PermissionError("Service smoke permits loopback sockets only")
    if event == "socket.getaddrinfo" and args[0] not in _LITERAL_LOOPBACKS:
        raise PermissionError("Service smoke permits literal loopback DNS targets only")


_ERROR_LINE = re.compile(r"\[(?:error|critical)\s*\]|\b(?:ERROR|CRITICAL):|Traceback|parse_failed")


def evaluate_worker_report(report: dict, stderr: str, return_code: int) -> dict:
    """Classify worker status and matching error lines without mutating its report."""
    error_lines = sum(bool(_ERROR_LINE.search(line)) for line in stderr.splitlines())
    result = {**report, "unexpected_error_logs": error_lines}
    if return_code or report.get("status") != "passed":
        return {**result, "status": "failed", "error": report.get("error", "Worker failed")}
    if error_lines:
        return {
            **result,
            "status": "failed",
            "error": f"Unexpected application error log lines: {error_lines}",
        }
    return result
