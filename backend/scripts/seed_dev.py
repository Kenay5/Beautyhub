"""Insert the minimum fictitious catalog needed for local development."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import PrivacyNoticeVersion, Service
from backend.app.infrastructure.settings import load_settings


DEV_SERVICES = (
    {
        "name": "Servicio demo básico",
        "description": "Servicio ficticio para pruebas locales.",
        "duration_minutes": 60,
        "price": Decimal("350.00"),
        "is_active": True,
        "available_chiconcuac": True,
        "available_texcoco": True,
    },
    {
        "name": "Servicio demo Texcoco",
        "description": "Servicio ficticio para pruebas locales.",
        "duration_minutes": 45,
        "price": Decimal("280.00"),
        "is_active": True,
        "available_chiconcuac": False,
        "available_texcoco": True,
    },
    {
        "name": "Uñas acrílicas demo",
        "description": "Servicio ficticio de uñas para pruebas visuales locales.",
        "duration_minutes": 120,
        "price": Decimal("450.00"),
        "is_active": True,
        "available_chiconcuac": True,
        "available_texcoco": True,
    },
    {
        "name": "Pestañas demo",
        "description": "Servicio ficticio de pestañas para pruebas visuales locales.",
        "duration_minutes": 90,
        "price": Decimal("380.00"),
        "is_active": True,
        "available_chiconcuac": True,
        "available_texcoco": True,
    },
    {
        "name": "Cabello demo",
        "description": "Servicio ficticio de cabello para pruebas visuales locales.",
        "duration_minutes": 60,
        "price": Decimal("300.00"),
        "is_active": True,
        "available_chiconcuac": True,
        "available_texcoco": True,
    },
)

DEV_PRIVACY_NOTICE = {
    "version": "development-local-notice-v1",
    "content": "Aviso de privacidad ficticio, exclusivo para pruebas locales de BeautyHub.",
    "published_at": datetime(2020, 1, 1, tzinfo=UTC),
    "valid_from": datetime(2020, 1, 1, tzinfo=UTC),
    "valid_until": None,
}


def seed_development_data() -> tuple[str, ...]:
    """Insert missing fictitious local data and return created descriptions."""

    settings = load_settings()
    engine = create_postgres_engine(settings.database_url)
    try:
        with engine.begin() as connection:
            existing = set(connection.scalars(select(Service.canonical_name)))
            created: list[str] = []
            for values in DEV_SERVICES:
                canonical_name = values["name"].strip().lower()
                if canonical_name in existing:
                    continue
                statement = (
                    insert(Service)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=[Service.canonical_name])
                )
                result = connection.execute(statement)
                if result.rowcount:
                    created.append(values["name"])
            notice_exists = connection.scalar(
                select(PrivacyNoticeVersion.privacy_notice_version_id).where(
                    PrivacyNoticeVersion.version == DEV_PRIVACY_NOTICE["version"]
                )
            )
            if notice_exists is None:
                connection.execute(insert(PrivacyNoticeVersion).values(**DEV_PRIVACY_NOTICE))
                created.append("aviso de privacidad ficticio")
            return tuple(created)
    finally:
        engine.dispose()


def main() -> None:
    """Run the local-only seed using the configured PostgreSQL database."""

    created = seed_development_data()
    if created:
        print("Datos ficticios creados: " + ", ".join(created))
    else:
        print("Los datos ficticios ya existían; no se crearon duplicados.")


if __name__ == "__main__":
    main()
