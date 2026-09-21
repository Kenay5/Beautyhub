"""Contract tests for the current public privacy notice endpoint."""

from datetime import date, time

from fastapi.testclient import TestClient

from backend.app.application.clock import FixedClock
from backend.app.application.get_current_privacy_notice import CurrentPrivacyNotice
from backend.app.domain.time import business_datetime
from backend.app.web.app import create_app
from backend.app.web.public_privacy_notice import (
    get_clock,
    get_current_privacy_notice_reader,
)


class FakeCurrentPrivacyNoticeReader:
    """Controlled reader used to prove the public response shape."""

    def __init__(self, notice: CurrentPrivacyNotice | None) -> None:
        self._notice = notice

    def get_current_privacy_notice(self, *, at):  # type: ignore[no-untyped-def]
        return self._notice


def test_public_privacy_notice_returns_only_the_current_version_and_content() -> None:
    app = create_app()
    app.dependency_overrides[get_current_privacy_notice_reader] = lambda: (
        FakeCurrentPrivacyNoticeReader(
            CurrentPrivacyNotice(
                version="development-notice-v1",
                content="Aviso ficticio para pruebas.",
            )
        )
    )
    app.dependency_overrides[get_clock] = lambda: FixedClock(
        business_datetime(date(2030, 6, 15), time(10))
    )

    with TestClient(app) as client:
        response = client.get("/api/public/privacy-notice")

    assert response.status_code == 200
    assert response.json() == {
        "version": "development-notice-v1",
        "content": "Aviso ficticio para pruebas.",
    }


def test_public_privacy_notice_reports_when_no_current_notice_exists() -> None:
    app = create_app()
    app.dependency_overrides[get_current_privacy_notice_reader] = lambda: (
        FakeCurrentPrivacyNoticeReader(None)
    )
    app.dependency_overrides[get_clock] = lambda: FixedClock(
        business_datetime(date(2030, 6, 15), time(10))
    )

    with TestClient(app) as client:
        response = client.get("/api/public/privacy-notice")

    assert response.status_code == 404
    assert response.json() == {"detail": "No hay un aviso de privacidad disponible."}
