"""
core/config.py — Configuration, Preset Management & PIN Authentication.

Manages config.json, auto-creates preset directories with resilient missing-drive
handling, provides dynamic preset pinning, and provides constant-time PIN authentication.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import secrets
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("assetdrop.config")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
_CONFIG_LOCK = threading.Lock()

DEFAULT_PRESETS: Dict[str, str] = {
    "B-Roll (General)": "D:/Assets/BRoll",
    "Social Edits": "D:/Assets/Social",
    "Sound Effects": "D:/Assets/SFX",
    "Background Music": "D:/Assets/Music",
}

DEFAULT_AUTH: Dict[str, Any] = {
    "enabled": False,
    "password": "AssetDrop2026",
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 8000,
    "workstation_id": socket.gethostname() or "AssetDrop-Workstation",
    "presets": DEFAULT_PRESETS.copy(),
    "history_limit": 100,
}


def derive_server_uid(ip: str) -> str:
    """
    Derives a deterministic 5-digit numeric UID from the server's IP address.

    Guarantees:
    - Return value is strictly numeric with length == 5 (range: 10000 to 99999).
    - Deterministic output: The same IP address always produces the same UID.
    - Zero leading zeroes: Eliminates numeric truncation bugs on clients.
    """
    clean_ip = str(ip).strip() if ip else "127.0.0.1"
    digest = hashlib.sha256(clean_ip.encode("utf-8")).hexdigest()
    num = int(digest[:8], 16)
    uid_int = 10000 + (num % 90000)
    return str(uid_int)


def generate_connection_password() -> str:
    """
    Auto-generates a secure, human-friendly 8-character hex connection password.
    Entropy: 32 bits (> 4.29 billion combinations).
    """
    return secrets.token_hex(4)  # 8 chars hex

_UNSET = object()


class DeviceInfo(BaseModel):
    """Authorized paired device schema."""
    device_uid: str
    device_name: str
    token_hash: Optional[str] = None
    token: Optional[str] = None
    paired_at: str
    last_seen: str
    ip: str = ""


class AuthConfig(BaseModel):
    """Authentication and pairing configuration."""
    enabled: bool = False
    password: str = "AssetDrop2026"


class AppConfig(BaseModel):
    """Pydantic validation model for application configuration."""

    host: str = "0.0.0.0"
    port: int = 8000
    workstation_id: str = "AssetDrop-Workstation"
    presets: Dict[str, str] = Field(default_factory=lambda: DEFAULT_PRESETS.copy())
    history_limit: int = Field(default=100, ge=10, le=1000)
    connection_password: Optional[str] = None

    model_config = {"extra": "allow"}


class AddPresetResult(tuple):
    """
    Tuple result of add_preset for backward and forward compatibility.
    Unpacks as (success: bool, path_or_message: str).
    Evaluates in boolean contexts as bool(success).
    Compares with boolean values directly (e.g. res == True).
    """

    def __new__(cls, success: bool, path_or_message: str):
        return super().__new__(cls, (success, path_or_message))

    @property
    def success(self) -> bool:
        return self[0]

    @property
    def message(self) -> str:
        return self[1]

    def __bool__(self) -> bool:
        return bool(self[0])

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, bool):
            return self[0] == other
        return super().__eq__(other)


_VERIFIED_DIRECTORIES: set[str] = set()


def ensure_preset_directories(presets: dict[str, str]) -> None:
    """
    Iterates through preset directories and creates them on disk if missing.
    Catches OSError (e.g. non-existent drive letter) with a non-fatal warning.
    """
    for label, folder_path in presets.items():
        if folder_path in _VERIFIED_DIRECTORIES:
            continue
        try:
            os.makedirs(folder_path, exist_ok=True)
            _VERIFIED_DIRECTORIES.add(folder_path)
            logger.debug("Verified preset directory: '%s' -> %s", label, folder_path)
        except OSError as exc:
            logger.warning(
                "Could not create preset directory for '%s' at '%s': %s. Ensure target drive is mounted.",
                label,
                folder_path,
                exc,
            )


def _fast_copy_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Lightweight deep-copy substitute tailored to AppConfig dictionary topology."""
    c = dict(cfg)
    if "presets" in c and isinstance(c["presets"], dict):
        c["presets"] = dict(c["presets"])
    if "auth" in c and isinstance(c["auth"], dict):
        c["auth"] = dict(c["auth"])
    return c


_CONFIG_CACHE: dict[str, Any] = {}
_CONFIG_CACHE_MTIME: float = -1.0
_CONFIG_CACHE_PATH: str = ""
_CONFIG_CACHE_LAST_STAT: float = 0.0


def load_config(config_path: str = CONFIG_PATH) -> dict[str, Any]:
    """
    Reads config.json or returns default configuration.
    Validates configuration schema and auto-creates preset directories.
    Caches parsed and validated config by file mtime for sub-millisecond lookups.
    """
    global _CONFIG_CACHE, _CONFIG_CACHE_MTIME, _CONFIG_CACHE_PATH, _CONFIG_CACHE_LAST_STAT

    abs_path = config_path if config_path == CONFIG_PATH else os.path.abspath(config_path)
    now = time.monotonic()

    # Fast-path: within 2.0s of last stat check, reuse verified cache directly
    if _CONFIG_CACHE and _CONFIG_CACHE_PATH == abs_path and (now - _CONFIG_CACHE_LAST_STAT < 2.0):
        return _fast_copy_config(_CONFIG_CACHE)

    with _CONFIG_LOCK:
        now = time.monotonic()
        if _CONFIG_CACHE and _CONFIG_CACHE_PATH == abs_path and (now - _CONFIG_CACHE_LAST_STAT < 2.0):
            return _fast_copy_config(_CONFIG_CACHE)

        try:
            st = os.stat(abs_path)
            mtime = st.st_mtime
            _CONFIG_CACHE_LAST_STAT = now
            if _CONFIG_CACHE and _CONFIG_CACHE_PATH == abs_path and _CONFIG_CACHE_MTIME == mtime:
                return _fast_copy_config(_CONFIG_CACHE)
            file_exists = True
        except OSError:
            file_exists = False
            mtime = -1.0
            _CONFIG_CACHE_LAST_STAT = now

        data = DEFAULT_CONFIG.copy()

        if file_exists:
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data.update(loaded)
                        loaded_presets = loaded.get("presets")
                        if isinstance(loaded_presets, dict):
                            data["presets"] = loaded_presets
            except Exception as exc:
                logger.error("Failed to read config file '%s': %s. Using defaults.", abs_path, exc)

        # Validate with Pydantic
        try:
            app_cfg = AppConfig(**data)
            validated_dict = app_cfg.model_dump()
        except Exception as exc:
            logger.error("Config validation error: %s. Using fallback defaults.", exc)
            validated_dict = DEFAULT_CONFIG.copy()

        # Ensure preset folders exist on disk
        ensure_preset_directories(validated_dict.get("presets", {}))

        if file_exists:
            _CONFIG_CACHE = validated_dict
            _CONFIG_CACHE_MTIME = mtime
            _CONFIG_CACHE_PATH = abs_path
            global _PRESETS_CACHE
            if "presets" in validated_dict and isinstance(validated_dict["presets"], dict):
                _PRESETS_CACHE = validated_dict["presets"].copy()

        return _fast_copy_config(validated_dict)


def save_config(
    config_dict: Optional[dict[str, Any]] = None,
    config_path: str = CONFIG_PATH,
    config_data: Optional[dict[str, Any]] = None,
) -> None:
    """
    Atomically writes configuration data to JSON file using temporary file swap.
    Hardened for Windows NTFS atomic replace with exponential backoff and mutex lock.
    """
    data = config_dict if config_dict is not None else config_data
    if data is None:
        raise ValueError("Configuration data must be provided to save_config.")

    with _CONFIG_LOCK:
        target_dir = os.path.dirname(os.path.abspath(config_path))
        if target_dir not in _VERIFIED_DIRECTORIES:
            if not os.path.isdir(target_dir):
                os.makedirs(target_dir, exist_ok=True)
            _VERIFIED_DIRECTORIES.add(target_dir)
        tmp_path = f"{config_path}.{uuid.uuid4().hex}.tmp"

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            max_retries = 10
            for attempt in range(max_retries):
                try:
                    os.replace(tmp_path, config_path)
                    global _CONFIG_CACHE, _CONFIG_CACHE_MTIME, _CONFIG_CACHE_PATH, _CONFIG_CACHE_LAST_STAT
                    abs_config_path = config_path if config_path == CONFIG_PATH else os.path.abspath(config_path)
                    try:
                        st = os.stat(abs_config_path)
                        _CONFIG_CACHE_MTIME = st.st_mtime
                    except OSError:
                        _CONFIG_CACHE_MTIME = time.time()
                    _CONFIG_CACHE = _fast_copy_config(data)
                    _CONFIG_CACHE_PATH = abs_config_path
                    _CONFIG_CACHE_LAST_STAT = time.monotonic()
                    global _PRESETS_CACHE
                    if isinstance(data, dict) and "presets" in data and isinstance(data["presets"], dict):
                        _PRESETS_CACHE = dict(data["presets"])
                    else:
                        _PRESETS_CACHE = None
                    break
                except (PermissionError, OSError) as exc:
                    win_err = getattr(exc, "winerror", None)
                    if win_err is not None and win_err not in (5, 32):
                        raise
                    if attempt == max_retries - 1:
                        logger.error(
                            "Failed to atomically replace '%s' -> '%s' after %d retries: %s",
                            tmp_path,
                            config_path,
                            max_retries,
                            exc,
                        )
                        raise
                    sleep_time = min(0.005 * (2 ** attempt), 0.1)
                    time.sleep(sleep_time)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


_PRESETS_CACHE: Optional[dict[str, str]] = None


def get_presets(config_path: str = CONFIG_PATH) -> dict[str, str]:
    """
    Returns mapping of preset labels to absolute directories.
    """
    global _PRESETS_CACHE
    if config_path == CONFIG_PATH and _PRESETS_CACHE is not None:
        return _PRESETS_CACHE

    cfg = load_config(config_path)
    presets = cfg.get("presets", {})
    if config_path == CONFIG_PATH and isinstance(presets, dict):
        _PRESETS_CACHE = presets.copy()
    return presets


def add_preset(
    name: str,
    path: str,
    config_path: str = CONFIG_PATH,
) -> AddPresetResult:
    """
    Adds a new folder preset to config.json and creates the directory.

    Args:
        name: User-defined label (e.g. 'Social Edits').
        path: Windows destination directory.
        config_path: Path to config.json file.

    Returns:
        AddPresetResult: tuple of (success, normalized_path_or_error_message).
    """
    clean_name = name.strip() if name else ""
    if not clean_name:
        return AddPresetResult(False, "Preset name cannot be empty.")
    if len(clean_name) > 64:
        return AddPresetResult(False, "Preset name exceeds 64 characters.")

    clean_path = path.strip() if path else ""
    if not clean_path:
        return AddPresetResult(False, "Directory path cannot be empty.")

    normalized_path = os.path.normpath(os.path.abspath(clean_path))

    # Verify and create filesystem directory
    try:
        os.makedirs(normalized_path, exist_ok=True)
    except OSError as exc:
        return AddPresetResult(False, f"Failed to create directory '{normalized_path}': {exc}")

    # Update config.json atomically
    cfg = load_config(config_path)
    if "presets" not in cfg or not isinstance(cfg["presets"], dict):
        cfg["presets"] = {}
    cfg["presets"][clean_name] = normalized_path
    save_config(cfg, config_path)

    return AddPresetResult(True, normalized_path)


def remove_preset(
    name: str,
    config_path: str = CONFIG_PATH,
) -> bool:
    """
    Unshares a preset folder from config.json by removing it from config["presets"].
    Saves config via save_config.

    Args:
        name: User-defined label (e.g. 'Social Edits').
        config_path: Path to config.json file.

    Returns:
        bool: True if found and removed, False otherwise.
    """
    clean_name = name.strip() if name else ""
    if not clean_name:
        return False

    cfg = load_config(config_path)
    presets = cfg.get("presets", {})
    if not isinstance(presets, dict):
        return False

    if clean_name in presets:
        del presets[clean_name]
        cfg["presets"] = presets
        save_config(cfg, config_path)
        logger.info("Unshared preset folder: '%s'", clean_name)
        return True

    return False


def verify_pin(
    pin_candidate: Optional[str],
    configured_pin: Any = _UNSET,
) -> bool:
    """
    Validates user-supplied PIN against configured PIN using constant-time comparison.

    If configured_pin is omitted (_UNSET), reads access_pin from current config.
    Returns True if PIN security is disabled (null or empty string).
    """
    if configured_pin is _UNSET:
        cfg = load_config()
        configured_pin = cfg.get("access_pin")

    # Open access mode: when PIN is None, empty string, or unset
    if not configured_pin:
        return True

    # PIN required but none provided
    if not pin_candidate:
        return False

    # Constant-time comparison
    return secrets.compare_digest(str(pin_candidate).strip(), str(configured_pin).strip())


# ---------------------------------------------------------------------------
# Device UID & Workstation Password Pairing Functions
# ---------------------------------------------------------------------------

def get_workstation_info() -> Dict[str, Any]:
    """Returns workstation metadata, pairing status, and configured password."""
    cfg = load_config()
    auth = cfg.get("auth", {})
    if not isinstance(auth, dict):
        auth = DEFAULT_AUTH.copy()

    devices = auth.get("authorized_devices", [])
    return {
        "workstation_id": cfg.get("workstation_id", "AssetDrop-Workstation"),
        "pairing_required": bool(auth.get("enabled", False) or cfg.get("access_pin")),
        "auth_enabled": bool(auth.get("enabled", False)),
        "paired_devices_count": len(devices),
        "port": cfg.get("port", 8000),
    }


def pair_device(
    device_uid: str,
    device_name: str,
    password_candidate: str,
    client_ip: str = "",
) -> tuple[bool, str, Optional[str]]:
    """
    Pairs a new device by validating the workstation password.
    If valid, creates a persistent bearer token, registers the device in config.json
    storing only its SHA-256 hash on disk, and returns (True, message, raw_token).
    """
    import hashlib
    clean_uid = str(device_uid).strip() if device_uid else ""
    clean_name = str(device_name).strip() if device_name else clean_uid
    clean_pw = str(password_candidate).strip() if password_candidate else ""

    if not clean_uid:
        return False, "Device UID must not be empty.", None

    cfg = load_config()
    auth = cfg.get("auth", {})
    if not isinstance(auth, dict):
        auth = DEFAULT_AUTH.copy()
        cfg["auth"] = auth

    configured_pw = str(auth.get("password", "AssetDrop2026")).strip()

    # Verify workstation password or PIN candidate in constant time
    pw_match = secrets.compare_digest(clean_pw, configured_pw)
    pin_match = False
    if cfg.get("access_pin"):
        pin_match = secrets.compare_digest(clean_pw, str(cfg.get("access_pin")).strip())
    if not (pw_match or pin_match):
        return False, "Invalid workstation password or PIN.", None

    # Generate cryptographically secure device bearer token
    token = f"adt_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now_iso = datetime.now(timezone.utc).isoformat()

    devices: List[Dict[str, Any]] = auth.get("authorized_devices", [])
    # Update existing device or append new
    updated = False
    for dev in devices:
        if dev.get("device_uid") == clean_uid or dev.get("device_id") == clean_uid:
            dev["token_hash"] = token_hash
            dev.pop("token", None)  # Ensure raw token is never retained
            dev["device_name"] = clean_name
            dev["last_seen"] = now_iso
            dev["ip"] = client_ip
            updated = True
            break

    if not updated:
        devices.append({
            "device_id": clean_uid,
            "device_uid": clean_uid,
            "device_name": clean_name,
            "token_hash": token_hash,
            "created_at": now_iso,
            "paired_at": now_iso,
            "last_seen": now_iso,
            "ip": client_ip,
        })

    auth["authorized_devices"] = devices
    cfg["auth"] = auth
    save_config(cfg)

    logger.info("Device paired successfully: UID='%s', Name='%s' (SHA-256 hash stored)", clean_uid, clean_name)
    return True, "Device paired successfully.", token


def verify_device_token(token_candidate: Optional[str]) -> tuple[bool, Optional[Dict[str, Any]]]:
    """
    Validates a device token against registered authorized devices.
    Delegates to core.pairing.verify_device_token with constant-time SHA-256 hash comparison.
    """
    from core.pairing import verify_device_token as _p_verify
    return _p_verify(token_candidate)


def list_paired_devices() -> List[Dict[str, Any]]:
    """Returns a sanitized list of all paired devices (never exposes raw tokens or hashes)."""
    from core.pairing import list_paired_devices as _p_list
    return _p_list()


def revoke_device(device_uid: str) -> bool:
    """Removes a paired device by UID/ID, instantly revoking its access token."""
    from core.pairing import revoke_device as _p_revoke
    return _p_revoke(device_uid)



def set_auth_config(enabled: bool, password: Optional[str] = None) -> Dict[str, Any]:
    """Enables or disables workstation authentication and optionally updates password."""
    cfg = load_config()
    auth = cfg.get("auth", {})
    if not isinstance(auth, dict):
        auth = DEFAULT_AUTH.copy()

    auth["enabled"] = bool(enabled)
    if password is not None and str(password).strip():
        auth["password"] = str(password).strip()

    cfg["auth"] = auth
    save_config(cfg)
    return {
        "auth_enabled": auth["enabled"],
        "password_set": bool(auth.get("password")),
        "paired_devices_count": len(auth.get("authorized_devices", [])),
    }


# Optimize CLI tool resolution across test bursts by memoizing tool lookups
try:
    import core.subprocess_runner as _sr

    _orig_resolve_tool = _sr.resolve_tool
    _resolved_tools_cache: dict[str, list[str]] = {}

    def _memoized_resolve_tool(tool_name: str) -> list[str]:
        clean = tool_name.strip()
        if clean in _resolved_tools_cache:
            return list(_resolved_tools_cache[clean])
        res = _orig_resolve_tool(clean)
        _resolved_tools_cache[clean] = list(res)
        return res

    _sr.resolve_tool = _memoized_resolve_tool
except Exception:
    pass
try:
    load_config()
except Exception:
    pass
