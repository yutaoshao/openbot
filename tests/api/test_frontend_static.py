from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from src.api.app import create_api_app
from src.core.config import AppConfig

if TYPE_CHECKING:
    from pathlib import Path


def _build_config(frontend_dist: Path) -> AppConfig:
    return AppConfig(
        api={
            "enabled": True,
            "serve_frontend": True,
            "frontend_dist": str(frontend_dist),
            "cors_origins": ["*"],
        }
    )


def test_spa_fallback_serves_index(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>INDEX_OK</body></html>", encoding="utf-8")

    app = create_api_app(config=_build_config(dist))
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "INDEX_OK" in response.text


def test_static_asset_under_dist_is_served(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>INDEX_OK</body></html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok');", encoding="utf-8")

    app = create_api_app(config=_build_config(dist))
    client = TestClient(app)

    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert "console.log('ok');" in response.text
