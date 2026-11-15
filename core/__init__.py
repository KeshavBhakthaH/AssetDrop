"""AssetDrop Core Package."""

from core.config import (
    AppConfig,
    load_config,
    save_config,
    get_presets,
    add_preset,
    verify_pin,
)
from core.routing import (
    detect_platform,
    build_download_command,
)
from core.subprocess_runner import (
    WINDOWS_CREATION_FLAGS,
    get_subprocess_kwargs,
    get_subprocess_env,
    resolve_tool,
    execute_download_job,
    run_command_stealth,
    extract_downloaded_filename,
    extract_error_details,
    ToolNotFoundError,
)
from core.queue_manager import (
    Job,
    QueueManager,
    get_queue_manager,
    enqueue_job,
    get_status,
)
from core.traversal import (
    get_windows_drives,
    browse_directory,
    scan_subfolders,
)

__all__ = [
    "AppConfig",
    "load_config",
    "save_config",
    "get_presets",
    "add_preset",
    "verify_pin",
    "detect_platform",
    "build_download_command",
    "WINDOWS_CREATION_FLAGS",
    "get_subprocess_kwargs",
    "get_subprocess_env",
    "resolve_tool",
    "execute_download_job",
    "run_command_stealth",
    "extract_downloaded_filename",
    "extract_error_details",
    "ToolNotFoundError",
    "Job",
    "QueueManager",
    "get_queue_manager",
    "enqueue_job",
    "get_status",
    "get_windows_drives",
    "browse_directory",
]
