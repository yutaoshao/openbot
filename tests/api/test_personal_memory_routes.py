from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import create_api_app
from src.api.routes import personal_memory
from src.memory.personal_profile import PersonalProfile


def test_dossier_edit_detects_manual_changes_and_rejects_traversal(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(personal_memory, "profile", PersonalProfile(tmp_path))
    document = tmp_path / "宠物" / "嘻嘻.md"
    document.parent.mkdir()
    document.write_text("# 嘻嘻\n\n## 已确认事实\n- 出生日期：2026-03-28\n")
    client = TestClient(create_api_app(), client=("127.0.0.1", 50000))
    path = "/api/personal-memory/宠物/嘻嘻.md"
    response = client.get(path)
    assert response.status_code == 200
    assert client.get("/api/personal-memory").json()["documents"] == ["宠物/嘻嘻.md"]
    document.write_text("# 嘻嘻\n\n## 已确认事实\n- 出生日期：2026-03-29\n")
    stale = client.put(
        path, json={"content": "# 嘻嘻\n错误覆盖", "revision": response.json()["revision"]}
    )
    assert stale.status_code == 409
    assert "2026-03-29" in document.read_text()
    assert client.get("/api/personal-memory/%2E%2E%2Fsecret.md").status_code in {404, 307}
