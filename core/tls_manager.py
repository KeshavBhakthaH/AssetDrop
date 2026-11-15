"""
core/tls_manager.py — Self-Signed TLS Certificate Generation & SHA-256 Fingerprint Pinning.

Implements Section 6 of AssetDrop Security Specification:
- Generates 2048-bit RSA private key and self-signed X.509 certificate on first run.
- SAN extensions: IP 127.0.0.1, LAN IP, DNS localhost, DNS assetdrop.local.
- Computes SHA-256 fingerprint for client-side pinning (encoded into pairing QR codes).
- Provides cert/key paths for Uvicorn HTTPS server.
- Supports HTTP fallback with clearly labeled security limitations for standard web clients.
"""

from __future__ import annotations

import datetime
import hashlib
import ipaddress
import logging
import os
import socket
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("assetdrop.tls")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS_DIR = os.path.join(PROJECT_ROOT, "certs")
CERT_FILE = os.path.join(CERTS_DIR, "cert.pem")
KEY_FILE = os.path.join(CERTS_DIR, "key.pem")


def get_local_lan_ip() -> str:
    """Discovers local Wi-Fi / LAN IPv4 address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def ensure_tls_certificate(
    certs_dir: str = CERTS_DIR,
    force_regenerate: bool = False,
) -> Tuple[str, str, str]:
    """
    Ensures that a valid self-signed certificate and private key exist on disk.
    If absent or force_regenerate is True, generates a new 2048-bit RSA certificate.

    Returns:
        (cert_path, key_path, sha256_fingerprint_hex)
    """
    os.makedirs(certs_dir, exist_ok=True)
    cert_path = os.path.join(certs_dir, "cert.pem")
    key_path = os.path.join(certs_dir, "key.pem")

    if not force_regenerate and os.path.isfile(cert_path) and os.path.isfile(key_path):
        fp = get_cert_fingerprint(cert_path)
        if fp:
            logger.debug("Existing TLS certificate found. SHA-256 Fingerprint: %s", fp)
            return cert_path, key_path, fp

    logger.info("Generating self-signed TLS certificate and private key in %s...", certs_dir)

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    # 1. Generate 2048-bit RSA private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # 2. Build Subject and SAN extensions
    lan_ip = get_local_lan_ip()
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AssetDrop Workstation Engine"),
        x509.NameAttribute(NameOID.COMMON_NAME, "AssetDrop-Host"),
    ])

    san_entries = [
        x509.DNSName("localhost"),
        x509.DNSName("assetdrop.local"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    try:
        san_entries.append(x509.IPAddress(ipaddress.ip_address(lan_ip)))
    except Exception:
        pass

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(san_entries),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    # 3. Write private key to key.pem (PEM format, no encryption)
    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(key_path, "wb") as f:
        f.write(key_bytes)

    # 4. Write certificate to cert.pem
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    with open(cert_path, "wb") as f:
        f.write(cert_bytes)

    # 5. Compute SHA-256 fingerprint
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    fingerprint = hashlib.sha256(cert_der).hexdigest()

    logger.info("Self-signed TLS certificate generated successfully. SHA-256 Fingerprint: %s", fingerprint)
    return cert_path, key_path, fingerprint


def get_cert_fingerprint(cert_path: str = CERT_FILE) -> Optional[str]:
    """Computes hexadecimal SHA-256 fingerprint of a PEM certificate file."""
    if not os.path.isfile(cert_path):
        return None
    try:
        from cryptography import x509
        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        from cryptography.hazmat.primitives import serialization
        cert_der = cert.public_bytes(serialization.Encoding.DER)
        return hashlib.sha256(cert_der).hexdigest()
    except Exception as exc:
        logger.warning("Could not calculate certificate fingerprint for '%s': %s", cert_path, exc)
        return None


def format_fingerprint_colon(fp_hex: str) -> str:
    """Formats 64-char hex string as colon-separated hex pairs (e.g. 72:44:00:...)."""
    clean = fp_hex.strip().lower()
    return ":".join(clean[i:i+2] for i in range(0, len(clean), 2))


def build_pairing_qr_url(
    lan_ip: str,
    port: int,
    token: str,
    use_https: bool = False,
    include_fingerprint: bool = True,
) -> Tuple[str, Optional[str]]:
    """
    Constructs the QR pairing URL with optional certificate fingerprint pinning parameter.

    Returns:
        (qr_url, fingerprint_or_none)
    """
    scheme = "https" if use_https else "http"
    base = f"{scheme}://{lan_ip}:{port}/pair?token={token}"

    fp = None
    if include_fingerprint:
        _, _, fp = ensure_tls_certificate()
        if fp:
            base += f"&fp={fp}"

    return base, fp
