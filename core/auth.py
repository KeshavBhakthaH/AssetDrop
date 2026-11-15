"""
core/auth.py — In-Memory Session Token Manager for Unified Simple Auth.

Requirement R1: Unified Simple Authentication.
Manages ephemeral in-memory session tokens (ads_<32 hex chars>) granted upon
successful UID + connection password login. All sessions reside strictly in memory;
zero disk persistence. Thread-safe and constant-time token verification.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import threading
from typing import Set

logger = logging.getLogger("assetdrop.auth")

_SESSION_LOCK = threading.Lock()
_ACTIVE_SESSIONS: Set[str] = set()


def create_session_token() -> str:
    """
    Generates a cryptographically secure in-memory session token and registers it.
    Token format: ads_<16 bytes hex> (36 chars total).
    """
    token = f"ads_{secrets.token_hex(16)}"
    with _SESSION_LOCK:
        _ACTIVE_SESSIONS.add(token)
    logger.info("Created new session token: %s...", token[:8])
    return token


def verify_session_token(token: str | None) -> bool:
    """
    Validates a session token against active in-memory sessions in constant time.
    Returns True if valid, False otherwise.
    """
    if not token or not isinstance(token, str):
        return False

    clean_token = token.strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    # Session tokens are strictly 36 ASCII chars (ads_<32 hex>). Non-ASCII tokens are invalid.
    if not clean_token or not clean_token.isascii():
        return False

    clean_bytes = clean_token.encode("utf-8")
    with _SESSION_LOCK:
        for active in _ACTIVE_SESSIONS:
            if hmac.compare_digest(clean_bytes, active.encode("utf-8")):
                return True
    return False


def revoke_session_token(token: str | None) -> bool:
    """
    Removes a session token from active in-memory sessions.
    Returns True if found and revoked, False otherwise.
    """
    if not token or not isinstance(token, str):
        return False

    clean_token = token.strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    if not clean_token or not clean_token.isascii():
        return False

    clean_bytes = clean_token.encode("utf-8")
    with _SESSION_LOCK:
        matched_token = None
        for active in _ACTIVE_SESSIONS:
            if hmac.compare_digest(clean_bytes, active.encode("utf-8")):
                matched_token = active
                break
        if matched_token:
            _ACTIVE_SESSIONS.discard(matched_token)
            logger.info("Revoked session token: %s...", clean_token[:8])
            return True
    return False


def get_active_session_count() -> int:
    """Returns count of currently active in-memory sessions."""
    with _SESSION_LOCK:
        return len(_ACTIVE_SESSIONS)


def clear_all_sessions() -> None:
    """Clears all in-memory sessions (useful for test resets)."""
    with _SESSION_LOCK:
        _ACTIVE_SESSIONS.clear()
