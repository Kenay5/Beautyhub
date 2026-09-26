"""Run the isolated browser-test app over HTTPS with an ephemeral certificate."""

from __future__ import annotations

import asyncio
import ipaddress
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _write_ephemeral_certificate(directory: Path) -> tuple[Path, Path]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]
    )
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    key_path = directory / "playwright-key.pem"
    certificate_path = directory / "playwright-certificate.pem"
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return certificate_path, key_path


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="beautyhub-playwright-") as temporary:
        certificate, private_key = _write_ephemeral_certificate(Path(temporary))
        health_app = FastAPI()

        @health_app.get("/health")
        def health() -> dict[str, str]:
            return {"status": "ready"}

        async def serve() -> None:
            https_server = uvicorn.Server(
                uvicorn.Config(
                    "backend.tests.e2e.admin_access.app:app",
                    host="127.0.0.1",
                    port=8443,
                    ssl_certfile=str(certificate),
                    ssl_keyfile=str(private_key),
                )
            )
            health_server = uvicorn.Server(
                uvicorn.Config(health_app, host="127.0.0.1", port=8000)
            )
            await asyncio.gather(https_server.serve(), health_server.serve())

        asyncio.run(serve())


if __name__ == "__main__":
    main()
