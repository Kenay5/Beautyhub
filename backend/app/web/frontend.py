"""Serve the compiled public and administrative React entry points."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


FRONTEND_DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"
_SECURITY_FLOW_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def register_frontend(app: FastAPI) -> None:
    """Register exact frontend routes without intercepting future API routes."""
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST_DIR / "assets", check_dir=False),
        name="frontend-assets",
    )

    @app.get("/", include_in_schema=False)
    async def public_frontend() -> FileResponse:
        return FileResponse(FRONTEND_DIST_DIR / "index.html")

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/", include_in_schema=False)
    async def administrative_frontend() -> FileResponse:
        return FileResponse(FRONTEND_DIST_DIR / "admin" / "index.html")

    @app.get("/admin/security-link", include_in_schema=False)
    @app.get("/admin/staff-activation", include_in_schema=False)
    @app.get("/admin/password-recovery", include_in_schema=False)
    @app.get("/admin/totp-replacement", include_in_schema=False)
    @app.get("/admin/email-change", include_in_schema=False)
    async def administrative_security_link_frontend() -> FileResponse:
        return FileResponse(
            FRONTEND_DIST_DIR / "admin" / "index.html",
            headers=_SECURITY_FLOW_HEADERS,
        )
