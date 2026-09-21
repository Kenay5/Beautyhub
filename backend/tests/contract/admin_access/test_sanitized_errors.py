"""T006 contract evidence for unexpected-error sanitization."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.web.sanitized_errors import unexpected_error_response


def test_t006_hides_sensitive_exception_values_from_response_and_logs(caplog) -> None:
    app = FastAPI()
    app.add_exception_handler(Exception, unexpected_error_response)
    prohibited_values = (
        "synthetic-password-value",
        "synthetic-private-code",
        "synthetic-security-token",
        "client@example.invalid",
        "5550101234",
        "synthetic SQL detail",
    )

    @app.get("/test-error")
    def raise_sensitive_error() -> None:
        raise RuntimeError(" | ".join(prohibited_values))

    with caplog.at_level(logging.INFO, logger="beautyhub.security"):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/test-error")

    assert response.status_code == 500
    assert response.json() == {"detail": "No fue posible completar la solicitud."}
    assert caplog.messages == ["event=unexpected_http_error outcome=failed"]
    for value in prohibited_values:
        assert value not in response.text
        assert value not in caplog.text
