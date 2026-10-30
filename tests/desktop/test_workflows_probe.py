"""The final packaged probe uses only immutable synthetic source data and redacted logs."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

MODULE = Path(__file__).parents[2] / "desktop/probe/desktop_workflows_probe.py"
spec = importlib.util.spec_from_file_location("desktop_workflows_probe", MODULE)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_workflow_fixture_contains_only_synthetic_offline_business_data(tmp_path):
    source = probe.synthetic_deployment(tmp_path, 12345)
    assert not (source / ".env").exists()
    assert "http://127.0.0.1:12345/v1" in (source / "config.yaml").read_text()
    hashes = probe.tree_hashes(source)
    with sqlite3.connect(source / "data/openbot.db") as database:
        assert database.execute("SELECT version FROM schema_version").fetchone()[0] == 11
        assert database.execute("SELECT status FROM schedules").fetchone()[0] == "active"
        assert (
            database.execute("SELECT content FROM messages").fetchone()[0]
            == "Synthetic imported history"
        )
    assert hashes == probe.tree_hashes(source)


def test_workflow_evidence_redacts_credentials_and_classifies_structured_errors(tmp_path):
    work = tmp_path / "work"
    evidence = tmp_path / "evidence"
    work.mkdir()
    (work / "phase.log").write_text(
        json.dumps(
            {"level": "error", "event": "synthetic_failure", "secret": probe.SYNTHETIC_SECRET}
        )
        + "\n"
    )
    assert probe._log_evidence(work, evidence) == 1
    assert probe.SYNTHETIC_SECRET not in (evidence / "phase.log").read_text()
