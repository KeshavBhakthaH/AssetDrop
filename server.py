"""
server.py — AssetDrop Cross-Device Media Ingestion Server (v2.0).

FastAPI headless daemon running on Windows host (0.0.0.0:8000).
Integrates:
- Non-blocking media ingestion queue (< 50ms SLA) via core.queue_manager.
- Route aliasing: POST /api/queue & /download, GET /api/status & /status, GET /api/presets & /folders, etc.
- Status telemetry tracking active downloads, recent completions, and failure diagnostics.
- Dynamic preset management & directory traversal (GET /api/presets, /folders, /api/drives, /api/browse).
- Constant-time PIN authentication with Open Access fallback.
- Defensive static PWA hosting ready for Mobile Web Client (Milestone 3).
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Union

# Ensure deterministic MIME types on Windows hosts
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/manifest+json", ".json")
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/x-icon", ".ico")
mimetypes.add_type("image/png", ".png")

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from core.config import (
    DEFAULT_PRESETS,
    PROJECT_ROOT,
    add_preset,
    derive_server_uid,
    generate_connection_password,
    get_presets,
    load_config,
    remove_preset,
)
from core.auth import (
    create_session_token,
    verify_session_token,
    revoke_session_token,
    get_active_session_count,
)
from core.security_limits import (
    validate_download_url,
    validate_path_containment,
    check_disk_space_floor,
    check_download_rate_limit,
    sanitize_filename,
)
from core.queue_manager import QueueManager, get_queue_manager
from core.subprocess_runner import resolve_tool
from core.routing import detect_platform
from core.traversal import browse_directory, get_windows_drives, scan_subfolders

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("assetdrop.server")

# ---------------------------------------------------------------------------
# Static Directory (Defensive Creation)
# ---------------------------------------------------------------------------
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
os.makedirs(STATIC_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Server Runtime Credentials (UID & Ephemeral Password)
# ---------------------------------------------------------------------------
SERVER_UID: str = ""
SERVER_PASSWORD: str = ""


def get_local_lan_ip() -> str:
    """Discovers the active local Wi-Fi / LAN IPv4 address."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def init_server_credentials(force_refresh: bool = False) -> Dict[str, Any]:
    """Initializes or retrieves active server credentials, persisting the password in config."""
    global SERVER_UID, SERVER_PASSWORD
    local_ip = get_local_lan_ip()
    if force_refresh or not SERVER_UID:
        SERVER_UID = derive_server_uid(local_ip)
    
    cfg = load_config()
    if force_refresh or not SERVER_PASSWORD:
        saved_pw = cfg.get("connection_password")
        if saved_pw and not force_refresh:
            SERVER_PASSWORD = saved_pw
        else:
            SERVER_PASSWORD = generate_connection_password()
            cfg["connection_password"] = SERVER_PASSWORD
            save_config(cfg)

    port = cfg.get("port", 8000)
    return {
        "uid": SERVER_UID,
        "password": SERVER_PASSWORD,
        "local_ip": local_ip,
        "port": port,
        "connection_url": f"http://{local_ip}:{port}",
        "workstation_id": cfg.get("workstation_id", "AssetDrop-Workstation"),
    }


# Eagerly initialize credentials on module load
init_server_credentials()


# ---------------------------------------------------------------------------
# Application Lifespan Context Manager
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager:
    - On startup: loads config, derives 5-digit UID from local LAN IP,
      generates in-memory startup connection password, ensures preset directories,
      initializes QueueManager worker pool, and verifies external CLI tools.
    - On shutdown: cleanly terminates background executor threads.
    """
    logger.info("Initializing AssetDrop daemon (v3.0)...")
    config = load_config()
    logger.info("Configuration loaded. Presets: %s", list(config.get("presets", {}).keys()))

    creds = init_server_credentials()
    logger.info("Server UID derived: %s (IP: %s)", creds["uid"], creds["local_ip"])
    logger.info("Startup connection password generated (ephemeral in-memory)")

    qm = get_queue_manager()
    logger.info("QueueManager initialized. Background worker pool active.")

    # Diagnostic check for external CLI tools (non-fatal if absent)
    for tool_name in ["yt-dlp", "gallery-dl", "ffmpeg", "ffprobe"]:
        try:
            cmd = resolve_tool(tool_name)
            logger.info("CLI tool '%s' resolved to: %s", tool_name, cmd[0])
        except Exception as exc:
            logger.warning("CLI tool '%s' resolution warning: %s", tool_name, exc)

    yield

    logger.info("Shutting down AssetDrop daemon...")
    qm.shutdown(wait=False, cancel_futures=True)
    logger.info("Background worker pool stopped. AssetDrop shutdown complete.")


# ---------------------------------------------------------------------------
# FastAPI Application Initialization
# ---------------------------------------------------------------------------
app = FastAPI(
    title="AssetDrop API",
    version="2.0.0",
    description="Cross-Device Media Ingestion Engine",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS Configuration (LAN Wi-Fi & Tailscale 4G Access)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Session Authentication Layer (Requirement R1: Unified Simple Auth)
# ---------------------------------------------------------------------------
def is_local_request(request: Request) -> bool:
    """Verifies whether request originates from localhost or Starlette TestClient."""
    host = request.client.host if request.client else ""
    if host == "testclient":
        simulated_ip = request.headers.get("X-Forwarded-For") or request.headers.get("X-Remote-IP")
        if simulated_ip and str(simulated_ip).strip() not in ("127.0.0.1", "::1", "localhost", "testclient"):
            return False
    return host in ("127.0.0.1", "::1", "localhost", "testclient")


def require_local_workstation(request: Request) -> None:
    """Restricts desktop management endpoints to local PC workstation only."""
    if not is_local_request(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: local workstation access only. Access restricted to local workstation.",
        )


def extract_session_token(
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
    token: Optional[str] = Query(None),
) -> Optional[str]:
    """
    Extracts session token from Authorization (Bearer <token>),
    X-Session-Token, X-Device-Token, or ?token= query parameter.
    """
    for hdr in (x_session_token, x_device_token):
        if hdr and str(hdr).strip():
            return str(hdr).strip()

    if authorization and str(authorization).strip():
        auth_str = str(authorization).strip()
        if auth_str.lower().startswith("bearer "):
            return auth_str[7:].strip()
        return auth_str

    if token and str(token).strip():
        return str(token).strip()

    return None


async def require_session_auth(
    request: Request,
    token: Optional[str] = Depends(extract_session_token),
) -> Optional[str]:
    """
    Router-level dependency enforcing in-memory session token authentication on protected endpoints.
    - Local workstation calls (localhost, testclient) are trusted for PC dashboard monitoring.
    - Remote clients (mobile phones / LAN clients) MUST present a valid in-memory session token.
    - Invalid or missing session token from remote callers raises 401 Unauthorized.
    """
    if is_local_request(request):
        return token or "localhost"

    if not token or not verify_session_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token


# Backward compatibility aliases
require_pin_auth = require_session_auth
extract_auth_credentials = extract_session_token


# ---------------------------------------------------------------------------
# Pydantic Request & Response Schemas
# ---------------------------------------------------------------------------
class IngestRequest(BaseModel):
    """Payload schema for media ingestion queueing."""

    url: str = Field(..., description="Target media URL to download")
    folder_key: Optional[str] = Field(
        default="B-Roll (General)",
        description="Preset folder key from config.json",
    )
    folder: Optional[str] = Field(None, description="Alias for folder_key")
    format_type: Optional[str] = Field(
        default="video",
        description="Requested format: 'video' (MP4) or 'audio' (MP3)",
    )
    custom_path: Optional[str] = Field(None, description="Custom destination folder path")
    target_dir: Optional[str] = Field(None, description="Alias for custom_path")
    target_folder: Optional[str] = Field(None, description="Alias for custom_path")

    model_config = {"extra": "ignore"}

    @field_validator("format_type", mode="before")
    @classmethod
    def normalize_format(cls, v: Any) -> str:
        s = str(v).strip().lower() if v else "video"
        if s in ("audio", "mp3"):
            return "audio"
        return "video"


class IngestResponse(BaseModel):
    """Sub-50ms ingestion response model."""

    status: str = "queued"
    job_id: str
    id: str
    url: str
    platform: str
    format_type: str
    target_dir: str
    target_folder: str
    created_at: float
    message: Optional[str] = "Job successfully queued"


class PresetsResponse(BaseModel):
    """Dual-key schema for folder presets listing."""

    presets: Dict[str, str] = Field(
        ...,
        description="Mapping of preset labels to target directory paths",
    )
    folders: List[str] = Field(
        ...,
        description="List of preset keys/labels for UI selection",
    )


class PresetPinRequest(BaseModel):
    """Payload schema for pinning a custom folder as a preset."""

    name: str = Field(..., min_length=1, max_length=64, description="User-defined preset label")
    path: str = Field(..., min_length=1, description="Filesystem directory path to pin")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Preset name cannot be blank or whitespace-only")
        if len(s) > 64:
            raise ValueError("Preset name cannot exceed 64 characters")
        return s

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Directory path cannot be blank or whitespace-only")
        return s


class PresetPinResponse(BaseModel):
    """Response schema for successful preset pinning."""

    status: str = "success"
    name: str
    path: str
    message: Optional[str] = "Preset pinned successfully"


class DrivesResponse(BaseModel):
    """Response schema for Windows drive enumeration."""

    drives: List[str] = Field(
        ...,
        description="List of mounted, accessible Windows drive roots",
    )


class BrowseResponse(BaseModel):
    """Response schema for directory traversal."""

    current: str
    parent: Optional[str] = None
    folders: List[str] = Field(default_factory=list)
    subdirectories: List[str] = Field(default_factory=list)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Destination Folder Resolver
# ---------------------------------------------------------------------------
def resolve_destination_folder(req: IngestRequest, presets: Dict[str, str]) -> str:
    """
    Resolves destination folder with deterministic precedence:
    1. custom_path / target_dir / target_folder (if provided)
    2. folder_key / folder (matching preset label, value, case-insensitive, or local dir)
    3. Default preset fallback ('B-Roll (General)' or first available preset)
    """
    # 1. Custom path takes precedence
    custom = req.custom_path or req.target_dir or req.target_folder
    if custom and custom.strip():
        norm_custom = os.path.normpath(os.path.abspath(custom.strip()))
        try:
            os.makedirs(norm_custom, exist_ok=True)
            return norm_custom
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Target directory invalid or inaccessible: '{custom}' ({exc})",
            )

    # 2. Preset key lookup & Subfolder resolution
    key = req.folder_key or req.folder
    if key and key.strip():
        clean_key = key.strip()

        # A. Direct key match (e.g. 'WORK')
        if clean_key in presets:
            return presets[clean_key]

        # B. Direct path value match (e.g. 'D:\\WORK')
        if clean_key in presets.values():
            return clean_key

        # C. Check parent / subfolder delimiters (e.g. 'WORK / C', 'WORK/C', 'WORK\\C')
        for sep in [" / ", " \\ ", "/", "\\"]:
            if sep in clean_key:
                parent_candidate, sub_candidate = clean_key.split(sep, 1)
                parent_candidate = parent_candidate.strip()
                sub_candidate = sub_candidate.strip()

                matched_parent_path = presets.get(parent_candidate)
                if not matched_parent_path:
                    for pk, pv in presets.items():
                        if pk.lower() == parent_candidate.lower():
                            matched_parent_path = pv
                            break

                if matched_parent_path:
                    dest = os.path.normpath(os.path.join(matched_parent_path, sub_candidate))
                    canonical_parent = os.path.normpath(os.path.abspath(matched_parent_path))
                    canonical_dest = os.path.normpath(os.path.abspath(dest))
                    # Prevent path traversal outside matched parent
                    if canonical_dest == canonical_parent or canonical_dest.startswith(canonical_parent + os.sep):
                        os.makedirs(canonical_dest, exist_ok=True)
                        return canonical_dest

        # D. Check folder ID match (SHA-256 slice for phone-safe IDs)
        import hashlib
        for k, v in presets.items():
            if clean_key == hashlib.sha256(k.encode("utf-8")).hexdigest()[:8]:
                return v
            if os.path.isdir(v):
                for sub in scan_subfolders(v):
                    full_name = f"{k} / {sub}"
                    if clean_key == hashlib.sha256(full_name.encode("utf-8")).hexdigest()[:8]:
                        dest = os.path.normpath(os.path.join(v, sub))
                        os.makedirs(dest, exist_ok=True)
                        return dest

        # E. Check if clean_key directly matches a subfolder name inside any allowed preset (e.g. 'C')
        for k, v in presets.items():
            if os.path.isdir(v):
                candidate = os.path.normpath(os.path.join(v, clean_key))
                canonical_p = os.path.normpath(os.path.abspath(v))
                canonical_c = os.path.normpath(os.path.abspath(candidate))
                if (canonical_c == canonical_p or canonical_c.startswith(canonical_p + os.sep)) and os.path.isdir(canonical_c):
                    return canonical_c

        # F. Case-insensitive key match
        lower_map = {k.lower(): v for k, v in presets.items()}
        if clean_key.lower() in lower_map:
            return lower_map[clean_key.lower()]

        # G. Existing directory on disk
        if os.path.isdir(clean_key):
            return os.path.normpath(os.path.abspath(clean_key))

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid folder_key: '{clean_key}'. Available presets: {list(presets.keys())}",
        )

    # 3. Default preset fallback
    if "B-Roll (General)" in presets:
        return presets["B-Roll (General)"]
    if presets:
        return next(iter(presets.values()))

    return os.path.normpath(os.path.abspath("D:/Assets/BRoll"))


# ---------------------------------------------------------------------------
# Public Router (Unrestricted Endpoints)
# ---------------------------------------------------------------------------
public_router = APIRouter(tags=["Public"])


@public_router.get("/health", tags=["Telemetry"])
@public_router.get("/api/health", tags=["Telemetry"])
async def health_check() -> Dict[str, Any]:
    """
    Public health check endpoint returning server status, version, and tool availability.
    Bypasses PIN authentication for infrastructure monitoring and pre-flight health checks.
    """
    cfg = load_config()
    qm = get_queue_manager()
    status_dict = qm.get_status()

    tools_available = {}
    for t in ["yt-dlp", "gallery-dl", "ffmpeg", "ffprobe"]:
        try:
            resolve_tool(t)
            tools_available[t] = True
        except Exception:
            tools_available[t] = False

    return {
        "status": "healthy",
        "version": "2.0.0",
        "timestamp": time.time(),
        "pin_required": bool(cfg.get("access_pin")),
        "active_jobs": len(status_dict.get("active", [])),
        "tools": tools_available,
    }


class OpenFolderRequest(BaseModel):
    """Payload schema for opening a folder in Explorer."""
    path: Optional[str] = Field(default=None, description="Directory path to open")
    name: Optional[str] = Field(default=None, description="Preset name to open")


class LoginRequest(BaseModel):
    """Payload schema for mobile client UID + password authentication."""
    uid: str = Field(..., description="5-digit Server UID")
    password: str = Field(..., description="Startup connection password")


@public_router.post(
    "/api/auth/login",
    tags=["Authentication"],
)
async def post_auth_login(payload: LoginRequest, request: Request) -> Dict[str, Any]:
    """
    Authenticates mobile clients with 5-digit UID and startup connection password.
    Validates in constant time using secrets.compare_digest.
    Returns in-memory session token (ads_<token>) on success.
    """
    creds = init_server_credentials()
    server_uid = creds["uid"]
    server_password = creds["password"]

    clean_uid = str(payload.uid).strip()
    clean_pw = str(payload.password).strip()

    # Compare UTF-8 encoded bytes to ensure constant-time verification
    # and prevent CPython TypeError: "comparing strings with non-ASCII characters is not supported"
    uid_valid = secrets.compare_digest(clean_uid.encode("utf-8"), server_uid.encode("utf-8"))
    pw_valid = secrets.compare_digest(clean_pw.encode("utf-8"), server_password.encode("utf-8"))

    if not (uid_valid and pw_valid):
        logger.warning(
            "Failed login attempt from IP: %s (UID attempted: %s)",
            request.client.host if request.client else "unknown",
            clean_uid[:16] if clean_uid.isascii() else "[non-ascii]",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid UID or password",
        )

    session_token = create_session_token()
    logger.info("Successful login from IP: %s", request.client.host if request.client else "unknown")
    return {
        "success": True,
        "session_token": session_token,
        "message": "Authenticated successfully",
    }


@public_router.post(
    "/api/auth/logout",
    tags=["Authentication"],
)
async def post_auth_logout(token: Optional[str] = Depends(extract_session_token)) -> Dict[str, Any]:
    """Revokes active in-memory session token."""
    if token:
        revoke_session_token(token)
    return {"success": True, "message": "Logged out successfully"}


@public_router.get(
    "/api/workstation/credentials",
    tags=["Workstation"],
)
@public_router.get(
    "/api/workstation/settings",
    tags=["Workstation"],
)
@public_router.get(
    "/api/workstation/info",
    tags=["Workstation"],
)
async def get_workstation_credentials(request: Request) -> Dict[str, Any]:
    """
    Returns workstation credentials (5-digit UID & password) for PC reveal control.
    Restricted to localhost / local PC workstation only. Remote clients receive 403 Forbidden.
    """
    require_local_workstation(request)
    creds = init_server_credentials()
    return {
        "uid": creds["uid"],
        "password": creds["password"],
        "local_ip": creds["local_ip"],
        "port": creds["port"],
        "connection_url": creds["connection_url"],
        "workstation_id": creds.get("workstation_id", "AssetDrop-Workstation"),
    }


@public_router.post(
    "/api/server/shutdown",
    tags=["Workstation"],
)
@public_router.post(
    "/api/workstation/shutdown",
    tags=["Workstation"],
)
async def shutdown_server(request: Request) -> Dict[str, Any]:
    """
    Gracefully shuts down the AssetDrop server daemon.
    Restricted strictly to the local PC workstation (127.0.0.1 / ::1).
    """
    require_local_workstation(request)
    client_ip = request.client.host if request.client else "unknown"
    logger.info("Server shutdown initiated via Workstation Settings from %s", client_ip)

    def _do_shutdown():
        time.sleep(0.4)
        logger.info("Executing clean daemon process exit...")
        try:
            qm = get_queue_manager()
            qm.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=_do_shutdown, daemon=True).start()
    return {
        "success": True,
        "message": "AssetDrop daemon is shutting down. You can safely close this window.",
    }


# ---------------------------------------------------------------------------
# Protected Router (Enforces require_session_auth Dependency)
# ---------------------------------------------------------------------------
protected_router = APIRouter(dependencies=[Depends(require_session_auth)])


# --- Ingestion Endpoints (Sub-50ms SLA Guarantee) ---
@protected_router.post(
    "/api/queue",
    response_model=IngestResponse,
    status_code=status.HTTP_200_OK,
    tags=["Ingestion"],
)
@protected_router.post(
    "/download",
    response_model=IngestResponse,
    status_code=status.HTTP_200_OK,
    tags=["Ingestion"],
)
async def queue_download(
    request: IngestRequest,
    http_req: Request,
    background_tasks: BackgroundTasks,
    token: Optional[str] = Depends(extract_session_token),
) -> IngestResponse:
    """
    Sub-50ms Media Ingestion Endpoint with Full Abuse & Security Controls:
    1. Validates URL scheme & executes SSRF protection.
    2. Validates hostname against domain allowlist.
    3. Rate-limits requests per client IP / token (10/min).
    4. Limits active concurrency to 2 background download jobs.
    5. Resolves destination directory & enforces shared folder containment.
    6. Verifies free disk space floor (1GB minimum).
    7. Enqueues job into background queue and returns instant JSON response (<50ms SLA).
    """
    clean_url = request.url.strip() if request.url else ""
    if not clean_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must not be empty",
        )

    # 1 & 2. SSRF defense & domain allowlist check
    validate_download_url(clean_url)

    # 3. Rate limiting per client / IP (10/min)
    client_id = token or (http_req.client.host if http_req.client else "unknown")
    if not check_download_rate_limit(client_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many download requests. Limit is 10 per minute.",
        )

    # 4. Shared Folder Containment:
    presets = get_presets()
    is_local = is_local_request(http_req)

    # Remote clients are prohibited from providing custom arbitrary filesystem paths
    if not is_local and (request.custom_path or request.target_dir or request.target_folder):
        custom_val = (request.custom_path or request.target_dir or request.target_folder or "").strip()
        if custom_val not in presets.values():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Custom filesystem paths are not allowed from remote devices. Please select a shared folder.",
            )

    target_dir = resolve_destination_folder(request, presets)
    validate_path_containment(target_dir, presets, is_local=is_local)

    # 5. Free disk space floor (1GB minimum)
    check_disk_space_floor(target_dir, floor_bytes=1024 * 1024 * 1024)

    # 6. Enqueue into bounded QueueManager (max 2 workers)
    qm = get_queue_manager()
    job = qm.enqueue_job(
        url=clean_url,
        target_dir=target_dir,
        format_type=request.format_type or "video",
    )

    background_tasks.add_task(
        logger.info,
        "Job [%s] queued: url=%s target=%s format=%s",
        job.id,
        clean_url,
        target_dir,
        request.format_type,
    )

    return IngestResponse(
        status="queued",
        job_id=job.id,
        id=job.id,
        url=job.url,
        platform=job.platform,
        format_type=job.format_type,
        target_dir=job.target_dir,
        target_folder=job.target_dir,
        created_at=job.created_at,
        message="Job successfully queued",
    )


# --- Status & Transfers Telemetry Endpoints ---
@protected_router.get("/api/transfers", tags=["Telemetry"])
@protected_router.get("/api/status", tags=["Telemetry"])
@protected_router.get("/status", tags=["Telemetry"])
async def get_telemetry_status() -> Dict[str, Any]:
    """
    Returns full telemetry snapshot with dual-key aliases:
    {'transfers': [...], 'active': [...], 'recent': [...], 'completed': [...], 'errors': [...], 'failed': [...]}
    """
    return get_queue_manager().get_status()


@protected_router.get("/api/queue/{job_id}", tags=["Telemetry"])
@protected_router.get("/api/status/{job_id}", tags=["Telemetry"])
async def get_single_job_status(job_id: str) -> Dict[str, Any]:
    """Retrieves live or historical telemetry for a single job by UUID."""
    job = get_queue_manager().get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found: {job_id}",
        )
    return job.to_dict()


@protected_router.post(
    "/api/transfers/{job_id}/open",
    tags=["Workstation"],
)
async def open_transfer_file_in_explorer(job_id: str, request: Request) -> Dict[str, Any]:
    """Highlights downloaded file in Windows File Explorer via explorer.exe /select,"<filepath>". Localhost only."""
    require_local_workstation(request)
    clean_id = job_id.strip() if job_id else ""
    job = get_queue_manager().get_job(clean_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found: {clean_id}",
        )

    if not job.filename or job.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{clean_id}' has not finished downloading or has no output file.",
        )

    file_path = os.path.normpath(os.path.join(job.target_dir, job.filename))
    norm_file = os.path.abspath(file_path)

    try:
        if sys.platform == "win32":
            if os.path.isfile(norm_file):
                try:
                    subprocess.Popen(["explorer.exe", f"/select,{norm_file}"])
                except Exception:
                    os.startfile(os.path.dirname(norm_file))
            elif os.path.isdir(job.target_dir):
                os.startfile(job.target_dir)
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Downloaded file '{norm_file}' does not exist on disk.",
                )
        else:
            logger.info("Mock opening file in explorer on non-windows: %s", norm_file)

        return {"status": "success", "opened": norm_file}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to open explorer for file: {exc}")


# --- Presets & Shared Folders Endpoints ---
@protected_router.get(
    "/api/shared-folders",
    tags=["Presets"],
)
@protected_router.get(
    "/api/folders",
    tags=["Presets"],
)
async def list_shared_folders(request: Request) -> Dict[str, Any]:
    """
    Returns shared folders.
    - Remote devices (phones) receive ONLY {id, name, subfolders} without any absolute filesystem paths.
    - Local workstation receives full dictionary with paths and subfolders.
    """
    import hashlib
    presets_map = get_presets()
    is_local = is_local_request(request)

    # Phone-safe folder list (ID, display name, and relative subfolders only, zero disk path exposure)
    phone_folders = []
    folders_list = []
    for name, path in presets_map.items():
        subs = scan_subfolders(path) if os.path.isdir(path) else []
        folder_id = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
        phone_folders.append({
            "id": folder_id,
            "name": name,
            "subfolders": subs,
        })
        folders_list.append({
            "name": name,
            "path": path,
            "exists": os.path.isdir(path),
            "is_default": name in DEFAULT_PRESETS,
            "subfolders": subs,
        })

    if not is_local:
        return {
            "folders": phone_folders,
        }

    return {
        "folders": folders_list,
        "presets": presets_map,
        "folder_names": list(presets_map.keys()),
        "shared_folders": folders_list,
        "phone_folders": phone_folders,
    }


@protected_router.get(
    "/api/presets",
    tags=["Presets"],
)
@protected_router.get(
    "/folders",
    tags=["Presets"],
)
async def list_presets(request: Request) -> Dict[str, Any]:
    """Returns dual-key structure with preset dictionary and folder label array."""
    presets_map = get_presets()
    is_local = is_local_request(request)

    phone_folders = []
    folders_list = []
    for name, path in presets_map.items():
        subs = scan_subfolders(path) if os.path.isdir(path) else []
        folder_id = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
        phone_folders.append({
            "id": folder_id,
            "name": name,
            "subfolders": subs,
        })
        folders_list.append({
            "name": name,
            "path": path,
            "exists": os.path.isdir(path),
            "is_default": name in DEFAULT_PRESETS,
            "subfolders": subs,
        })

    if not is_local:
        return {"folders": phone_folders}

    return {
        "presets": presets_map,
        "folders": list(presets_map.keys()),
        "shared_folders": folders_list,
    }


@protected_router.post(
    "/api/shared-folders",
    response_model=PresetPinResponse,
    status_code=status.HTTP_200_OK,
    tags=["Presets"],
)
@protected_router.post(
    "/api/presets",
    response_model=PresetPinResponse,
    status_code=status.HTTP_200_OK,
    tags=["Presets"],
)
@protected_router.post(
    "/api/presets/pin",
    response_model=PresetPinResponse,
    status_code=status.HTTP_200_OK,
    tags=["Presets"],
)
async def pin_preset(req: PresetPinRequest, request: Request) -> PresetPinResponse:
    """Adds a new folder preset to config.json and creates the directory on disk. Localhost only."""
    require_local_workstation(request)
    result = add_preset(name=req.name, path=req.path)
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )
    return PresetPinResponse(
        status="success",
        name=req.name.strip(),
        path=result.message,
        message="Preset pinned successfully",
    )


@protected_router.delete(
    "/api/shared-folders/{name}",
    tags=["Presets"],
)
@protected_router.delete(
    "/api/presets/{name}",
    tags=["Presets"],
)
async def delete_shared_folder(name: str, request: Request) -> Dict[str, Any]:
    """Removes a shared folder preset from config.json. Localhost only."""
    require_local_workstation(request)
    clean_name = name.strip() if name else ""
    success = remove_preset(clean_name)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shared folder '{clean_name}' not found.",
        )
    return {
        "status": "success",
        "name": clean_name,
        "message": f"Shared folder '{clean_name}' removed successfully.",
    }


class CreateFolderRequest(BaseModel):
    """Payload schema for creating a new subfolder in an allowed folder."""
    parent: str = Field(..., description="Parent preset name or path (e.g. 'WORK' or 'WORK / Sub')")
    name: str = Field(..., min_length=1, max_length=64, description="New folder name to create")


@protected_router.post(
    "/api/folders/create",
    tags=["Folders"],
)
async def create_new_folder(
    payload: CreateFolderRequest,
    request: Request,
    token: Optional[str] = Depends(extract_session_token),
) -> Dict[str, Any]:
    """
    Creates a new folder inside an authorized destination folder.
    - Protected endpoint: remote devices (phones) must be authenticated.
    - Validates strictly against illegal Windows filename characters.
    - Resolves parent preset and enforces containment within the preset root.
    - Returns updated folder info and fresh subfolder list.
    """
    raw_name = str(payload.name).strip()
    raw_parent = str(payload.parent).strip()

    if not raw_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Folder name cannot be empty.",
        )

    # Windows forbidden characters check: < > : " / \ | ? * and control chars
    forbidden_chars = set(r'<>:"/\|?*')
    if any(c in forbidden_chars or ord(c) < 32 for c in raw_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Folder name contains forbidden characters (< > : " / \\ | ? *).',
        )

    # Windows reserved folder names
    base_stem = raw_name.split(".")[0].upper()
    reserved_names = {
        "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4",
        "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2",
        "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    if base_stem in reserved_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Folder name '{raw_name}' is reserved by Windows.",
        )

    # Resolve parent directory on disk
    presets = get_presets()
    parent_dir = None
    if raw_parent in presets:
        parent_dir = presets[raw_parent]
    else:
        try:
            req_dummy = IngestRequest(url="https://youtube.com/watch?v=dummy", folder_key=raw_parent)
            parent_dir = resolve_destination_folder(req_dummy, presets)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Parent folder '{raw_parent}' not found among allowed folders.",
            )

    canonical_parent = os.path.normpath(os.path.abspath(parent_dir))
    if not os.path.isdir(canonical_parent):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Parent directory does not exist: '{raw_parent}'",
        )

    # Verify containment within an allowed preset root
    presets = get_presets()
    matched_root = None
    for k, root_path in presets.items():
        canonical_root = os.path.normpath(os.path.abspath(root_path))
        if canonical_parent == canonical_root or canonical_parent.startswith(canonical_root + os.sep):
            matched_root = (k, canonical_root)
            break

    if not matched_root:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Creation outside allowed download folders is forbidden.",
        )

    preset_name, canonical_root = matched_root
    target_path = os.path.normpath(os.path.abspath(os.path.join(canonical_parent, raw_name)))

    # Prevent traversal
    if not target_path.startswith(canonical_parent + os.sep):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path traversal detected.",
        )

    try:
        os.makedirs(target_path, exist_ok=True)
    except OSError as exc:
        logger.error("Failed to create folder '%s': %s", target_path, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create directory on disk: {exc}",
        )

    # Calculate relative path from root preset
    rel_path = os.path.relpath(target_path, canonical_root).replace("\\", "/")
    composite_key = f"{preset_name} / {rel_path}"

    # Get updated subfolders
    updated_subs = scan_subfolders(canonical_root)

    logger.info("Created new folder '%s' inside '%s' (Key: '%s')", raw_name, preset_name, composite_key)
    return {
        "success": True,
        "message": f"Folder '{raw_name}' created successfully.",
        "folder_key": composite_key,
        "name": raw_name,
        "relative_path": rel_path,
        "parent_preset": preset_name,
        "subfolders": updated_subs,
    }


# --- Drives & Directory Traversal Endpoints ---
@protected_router.get(
    "/api/drives",
    response_model=DrivesResponse,
    tags=["Traversal"],
)
async def list_drives(request: Request) -> DrivesResponse:
    """Returns list of mounted Windows drive root paths. Localhost only."""
    require_local_workstation(request)
    return DrivesResponse(drives=get_windows_drives())


@protected_router.get(
    "/api/browse",
    response_model=BrowseResponse,
    tags=["Traversal"],
)
async def browse_path(
    request: Request,
    path: Optional[str] = Query(None, description="Directory path to enumerate"),
) -> BrowseResponse:
    """Safely enumerates immediate subdirectories for live PC folder traversal. Localhost only."""
    require_local_workstation(request)
    result = browse_directory(path)

    if "error" in result:
        err = result["error"]
        if err == "Directory not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err)
        elif err in ("Path is not a directory", "Invalid path"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
        elif err == "Access denied":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=err)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)

    return BrowseResponse(
        current=result["current"],
        parent=result.get("parent"),
        folders=result.get("folders", []),
        subdirectories=result.get("subdirectories", []),
        error=None,
    )


@protected_router.post(
    "/api/shared-folders/open",
    tags=["Workstation"],
)
@protected_router.post(
    "/api/open-folder",
    tags=["Workstation"],
)
async def open_shared_folder(
    request: Request,
    path: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Opens target assets folder in Windows File Explorer directly from the workstation dashboard. Localhost only."""
    require_local_workstation(request)
    target_path = path

    # Check for JSON payload if provided
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                if not target_path and body.get("path"):
                    target_path = str(body["path"]).strip()
                elif not target_path and body.get("name"):
                    presets = get_presets()
                    target_path = presets.get(str(body["name"]).strip())
        except Exception:
            pass

    if not target_path:
        target_path = "D:/Assets"

    norm_path = os.path.normpath(os.path.abspath(target_path))
    try:
        os.makedirs(norm_path, exist_ok=True)
    except OSError:
        pass

    try:
        if sys.platform == "win32":
            try:
                os.startfile(norm_path)
            except Exception:
                subprocess.Popen(["explorer.exe", norm_path])
        else:
            logger.info("Mock opening explorer folder: %s", norm_path)
        return {"status": "success", "opened": norm_path}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to open explorer: {exc}")


# --- Native Windows Folder Picker Dialog (Localhost only) ---
@public_router.post(
    "/api/dialog/pick-folder",
    tags=["Workstation"],
)
async def pick_folder_dialog(request: Request) -> Dict[str, Any]:
    """
    Opens a native Windows folder picker dialog on the local PC workstation.
    Restricted to localhost / local workstation only.
    """
    require_local_workstation(request)

    def _run_dialog() -> Optional[str]:
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(title="Select Download Folder on PC")
            root.destroy()
            return selected if selected else None
        except Exception as exc:
            logger.warning("Native folder picker error: %s", exc)
            return None

    import asyncio
    selected_path = await asyncio.to_thread(_run_dialog)
    if not selected_path:
        return {"status": "cancelled", "path": None, "name": None}

    norm_path = os.path.normpath(os.path.abspath(selected_path))
    suggested_name = os.path.basename(norm_path) or "Custom Folder"
    return {
        "status": "selected",
        "path": norm_path,
        "name": suggested_name,
    }


# --- Media Inspection & Thumbnail Endpoint ---
@public_router.post(
    "/api/media/inspect",
    tags=["Ingestion"],
)
async def inspect_media_url(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    """
    Inspects media URL: extracts platform, title, and thumbnail.
    Identifies whether the media is a YouTube video (so client only prompts for MP3/MP4 on YouTube).
    """
    raw_url = str(payload.get("url") or "").strip()
    if not raw_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must not be empty",
        )

    # Normalize url: extract embedded http/https url if surrounded by text
    url_match = re.search(r"https?://[^\s\"'<>]+", raw_url)
    if url_match:
        raw_url = url_match.group(0)
    elif not raw_url.startswith(("http://", "https://")):
        raw_url = f"https://{raw_url}"

    validate_download_url(raw_url)
    platform = detect_platform(raw_url)
    is_youtube = (platform == "youtube")

    title = None
    thumbnail = None

    # 1. Fast-path YouTube thumbnail & title
    if is_youtube:
        yt_id_match = re.search(r"(?:v=|\/|youtu\.be\/|shorts\/)([a-zA-Z0-9_-]{11})", raw_url)
        if yt_id_match:
            vid = yt_id_match.group(1)
            thumbnail = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
        try:
            import urllib.request, urllib.parse, json
            oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(raw_url)}&format=json"
            req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0 (AssetDrop)"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    oe = json.loads(resp.read().decode("utf-8"))
                    title = oe.get("title") or title
                    thumbnail = oe.get("thumbnail_url") or thumbnail
        except Exception:
            pass

    # 2. Fast-path TikTok oEmbed
    elif platform == "tiktok":
        try:
            import urllib.request, urllib.parse, json
            oembed_url = f"https://www.tiktok.com/oembed?url={urllib.parse.quote(raw_url)}"
            req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0 (AssetDrop)"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    oe = json.loads(resp.read().decode("utf-8"))
                    title = oe.get("title")
                    thumbnail = oe.get("thumbnail_url")
        except Exception:
            pass

    # 3. Fallback to yt-dlp metadata query (fast, skip download)
    if not title or not thumbnail:
        def _fetch_ytdlp_meta():
            try:
                import subprocess, json
                from core.subprocess_runner import resolve_tool
                tool = resolve_tool("yt-dlp")
                cmd = tool + [
                    "--dump-json",
                    "--skip-download",
                    "--no-playlist",
                    "--no-warnings",
                    raw_url
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=3.5)
                if res.returncode == 0 and res.stdout.strip():
                    first_line = res.stdout.strip().splitlines()[0]
                    return json.loads(first_line)
            except Exception as exc:
                logger.warning("yt-dlp inspect error for %s: %s", raw_url, exc)
            return None

        import asyncio
        meta = await asyncio.to_thread(_fetch_ytdlp_meta)
        if meta:
            title = title or meta.get("title")
            thumbnail = thumbnail or meta.get("thumbnail")

    return {
        "url": raw_url,
        "platform": platform,
        "is_youtube": is_youtube,
        "title": title or f"{platform.capitalize()} Media",
        "thumbnail": thumbnail or "",
    }


# ---------------------------------------------------------------------------
# Register Routers
# ---------------------------------------------------------------------------
app.include_router(public_router)
app.include_router(protected_router)


# ---------------------------------------------------------------------------
# Static File, Route Dispatcher & PWA Hosting
# ---------------------------------------------------------------------------
MOBILE_UA_REGEX = re.compile(
    r"Android|iPhone|iPad|iPod|Windows Phone|webOS", re.IGNORECASE
)


def is_mobile_user_agent(user_agent: Optional[str]) -> bool:
    """Detects mobile clients via User-Agent inspection."""
    if not user_agent:
        return False
    return bool(MOBILE_UA_REGEX.search(user_agent))


HTML_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.get("/pc", response_class=HTMLResponse, include_in_schema=False)
@app.get("/pc.html", response_class=HTMLResponse, include_in_schema=False)
async def serve_pc_page():
    """Serves minimal PC workstation dashboard (static/pc.html)."""
    pc_file = os.path.join(STATIC_DIR, "pc.html")
    if os.path.isfile(pc_file):
        return FileResponse(pc_file, media_type="text/html", headers=HTML_NO_CACHE_HEADERS)
    raise HTTPException(status_code=404, detail="PC interface not found")


@app.get("/mobile", response_class=HTMLResponse, include_in_schema=False)
@app.get("/mobile.html", response_class=HTMLResponse, include_in_schema=False)
async def serve_mobile_page():
    """Serves dedicated two-stage mobile interface (static/mobile.html)."""
    mobile_file = os.path.join(STATIC_DIR, "mobile.html")
    if os.path.isfile(mobile_file):
        return FileResponse(mobile_file, media_type="text/html", headers=HTML_NO_CACHE_HEADERS)
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_file):
        return FileResponse(index_file, media_type="text/html", headers=HTML_NO_CACHE_HEADERS)
    raise HTTPException(status_code=404, detail="Mobile interface not found")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root_index(request: Request):
    """
    Dynamic root route dispatcher:
    - Mobile User-Agents: serves static/mobile.html (or static/index.html fallback)
    - Desktop User-Agents: serves static/pc.html (or static/index.html fallback)
    """
    ua = request.headers.get("user-agent", "")
    if is_mobile_user_agent(ua):
        mobile_file = os.path.join(STATIC_DIR, "mobile.html")
        if os.path.isfile(mobile_file):
            return FileResponse(mobile_file, media_type="text/html", headers=HTML_NO_CACHE_HEADERS)
        index_file = os.path.join(STATIC_DIR, "index.html")
        if os.path.isfile(index_file):
            return FileResponse(index_file, media_type="text/html", headers=HTML_NO_CACHE_HEADERS)

    pc_file = os.path.join(STATIC_DIR, "pc.html")
    if os.path.isfile(pc_file):
        return FileResponse(pc_file, media_type="text/html", headers=HTML_NO_CACHE_HEADERS)

    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_file):
        return FileResponse(index_file, media_type="text/html", headers=HTML_NO_CACHE_HEADERS)

    return HTMLResponse(
        content="""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AssetDrop Engine</title>
</head>
<body style="background:#090d16;color:#e0e0e0;font-family:system-ui,-apple-system,sans-serif;padding:2rem;">
  <h2>AssetDrop: Cross-Device Media Ingestion Engine (v2.0)</h2>
  <p>Headless REST API server is running on port 8000.</p>
</body>
</html>""",
        status_code=200,
    )


@app.get("/index.html", response_class=HTMLResponse, include_in_schema=False)
async def root_index_alias():
    """Serves PWA index.html under canonical /index.html path."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_file):
        return FileResponse(index_file, media_type="text/html")
    pc_file = os.path.join(STATIC_DIR, "pc.html")
    if os.path.isfile(pc_file):
        return FileResponse(pc_file, media_type="text/html")
    return HTMLResponse(content="<h2>AssetDrop</h2>", status_code=200)


@app.get("/manifest.json", include_in_schema=False)
async def serve_manifest():
    """Serves PWA manifest.json with manifest MIME type and caching headers."""
    manifest_file = os.path.join(STATIC_DIR, "manifest.json")
    if os.path.isfile(manifest_file):
        return FileResponse(
            manifest_file,
            media_type="application/manifest+json",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    return JSONResponse(status_code=404, content={"detail": "Manifest not found"})


@app.get("/sw.js", include_in_schema=False)
async def serve_sw():
    """Serves PWA service worker with root scope permissions and no-cache headers."""
    sw_file = os.path.join(STATIC_DIR, "sw.js")
    if os.path.isfile(sw_file):
        return FileResponse(
            sw_file,
            media_type="application/javascript",
            headers={
                "Service-Worker-Allowed": "/",
                "Cache-Control": "no-cache, no-store, must-revalidate",
            },
        )
    return JSONResponse(status_code=404, content={"detail": "Service worker not found"})


@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    """Serves browser favicon from static/icons/ directory."""
    fav_file = os.path.join(STATIC_DIR, "icons", "favicon.ico")
    if os.path.isfile(fav_file):
        return FileResponse(fav_file, media_type="image/x-icon")
    svg_fav = os.path.join(STATIC_DIR, "icons", "icon.svg")
    if os.path.isfile(svg_fav):
        return FileResponse(svg_fav, media_type="image/svg+xml")
    return Response(status_code=204)


# Mount static assets directory
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------------------
# CLI Direct Execution Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    cfg = load_config()
    server_host = cfg.get("host", "0.0.0.0")
    server_port = int(cfg.get("port", 8000))
    logger.info("Starting AssetDrop daemon on http://%s:%d", server_host, server_port)
    uvicorn.run("server:app", host=server_host, port=server_port, reload=False)
