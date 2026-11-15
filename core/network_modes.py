"""
core/network_modes.py — Deprecated Legacy Network Modes Module.

DEPRECATION NOTICE:
As part of Requirement R1 (Unified Simple Authentication), network mode switching
('public' vs 'trusted') has been removed. Unified Simple Authentication enforces
the same secure 5-digit UID and startup connection password across all networks.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("assetdrop.network_modes")

MODE_PUBLIC = "public"
MODE_TRUSTED = "trusted"
PUBLIC_PAIRING_TTL = 60.0
TRUSTED_PAIRING_TTL = 300.0


def get_network_mode() -> str:
    """Deprecated: returns 'trusted' default."""
    return MODE_TRUSTED


def set_network_mode(mode: str) -> Dict[str, Any]:
    """Deprecated: no-op stub."""
    return {
        "network_mode": MODE_TRUSTED,
        "is_public": False,
        "pairing_ttl_seconds": TRUSTED_PAIRING_TTL,
    }


def get_pairing_ttl_for_mode(mode: Optional[str] = None) -> float:
    """Deprecated: returns default TTL."""
    return TRUSTED_PAIRING_TTL


def open_pairing_window(duration_seconds: Optional[float] = None) -> float:
    """Deprecated: no-op stub."""
    return 0.0


def is_pairing_allowed() -> bool:
    """Deprecated: returns True."""
    return True


def close_pairing_window() -> None:
    """Deprecated: no-op stub."""
    pass
