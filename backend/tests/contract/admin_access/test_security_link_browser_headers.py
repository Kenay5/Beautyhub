"""T028 contract evidence for a non-referring, non-cacheable link entry page."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.web import frontend


def test_t028_security_link_entry_disables_cache_referrer_and_framing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    admin_dir = tmp_path / "admin"
    admin_dir.mkdir()
    (admin_dir / "index.html").write_text("<!doctype html><title>Admin</title>", encoding="utf-8")
    monkeypatch.setattr(frontend, "FRONTEND_DIST_DIR", tmp_path)
    app = FastAPI()
    frontend.register_frontend(app)

    with TestClient(app) as client:
        response = client.get("/admin/security-link")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
