"""
core/pairing.py — Deprecated Legacy Pairing Module.

DEPRECATION NOTICE:
As part of Requirement R1 (Unified Simple Authentication), legacy QR pairing,
ephemeral pairing windows, and disk-backed device registries have been removed.
Unified Simple Authentication is now handled via 5-digit UID and startup connection
passwords in core/config.py and in-memory session tokens in core/auth.py.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("assetdrop.pairing")

DEFAULT_PAIRING_TTL = 300.0


def generate_pairing_token(ttl_seconds: float = DEFAULT_PAIRING_TTL) -> Tuple[str, float]:
    """Deprecated: Generates a stub pairing token."""
    logger.warning("generate_pairing_token is deprecated. Use Unified Simple Auth.")
    return secrets.token_urlsafe(16), 0.0


def validate_and_consume_pairing_token(token: Optional[str]) -> bool:
    """Deprecated: Always returns False under Unified Simple Auth."""
    return False


def record_and_check_rate_limit(client_ip: str) -> bool:
    """Deprecated: Rate limit stub."""
    return True


def reset_rate_limit(client_ip: Optional[str] = None) -> None:
    """Deprecated: Rate limit reset stub."""
    pass


def register_paired_device(
    user_agent: str = "",
    client_ip: str = "",
    device_name_override: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Deprecated device registration stub."""
    return secrets.token_hex(16), {
        "device_id": "legacy",
        "device_name": device_name_override or "Legacy Device",
        "created_at": "",
    }


def hash_device_token(token: str) -> str:
    """Deprecated hash stub."""
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_device_token(token_candidate: Optional[str]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Deprecated: Checks in-memory session token for backward compatibility."""
    from core.auth import verify_session_token
    if verify_session_token(token_candidate):
        return True, {"device_id": "session_user", "device_name": "Authenticated Session"}
    return False, None


def list_paired_devices() -> List[Dict[str, Any]]:
    """Deprecated: returns empty list."""
    return []


def revoke_device(device_uid: str) -> bool:
    """Deprecated device revocation stub."""
    return False
