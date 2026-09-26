"""Security headers for administrative HTML and API responses."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response


ADMINISTRATIVE_CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'none'",
        "connect-src 'self'",
        "font-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "img-src 'self' data:",
        "object-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
    )
)


def register_administrative_security_headers(app: FastAPI) -> None:
    """Apply the approved no-cache, referrer, CSP and framing policy."""

    @app.middleware("http")
    async def add_administrative_security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if _is_administrative_path(request.url.path):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = (
                ADMINISTRATIVE_CONTENT_SECURITY_POLICY
            )
            response.headers["X-Frame-Options"] = "DENY"
        return response


def _is_administrative_path(path: str) -> bool:
    return path == "/admin" or path.startswith(("/admin/", "/api/admin/"))
