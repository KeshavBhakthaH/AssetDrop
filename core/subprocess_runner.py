"""
core/subprocess_runner.py — Resilient CLI Tool Resolution & Stealth Subprocess Engine.

Implements:
1. Multi-tier tool resolution (shutil.which -> Python Scripts -> python -m -> local bin).
2. Windows stealth & below-normal priority flags (CREATE_NO_WINDOW | 0x00004000).
3. Subprocess environment synthesis with dynamic PATH prepending.
4. Robust stdout/stderr output capture, stage-prioritized filename extraction,
   and clean diagnostic error parsing.
5. execute_download_job runner supporting live progress updates and error telemetry.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import shutil
import subprocess
import sys
import sysconfig
from typing import Optional, Tuple

logger = logging.getLogger("assetdrop.subprocess")

# ---------------------------------------------------------------------------
# Windows Process Creation Flags
# ---------------------------------------------------------------------------
IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

# 0x08000000 | 0x00004000 = 0x08004000 (134234112)
WINDOWS_CREATION_FLAGS = (
    CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS if IS_WINDOWS else 0
)

# Project root bin directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_BIN_DIR = os.path.join(PROJECT_ROOT, "bin")

# Python package module map
PYTHON_MODULE_MAP = {
    "yt-dlp": "yt_dlp",
    "gallery-dl": "gallery_dl",
}


class ToolNotFoundError(FileNotFoundError):
    """Raised when an external CLI executable or Python module cannot be resolved."""

    pass


def get_subprocess_kwargs() -> dict:
    """
    Returns platform-appropriate subprocess kwargs.
    On Windows, sets creationflags = CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS.
    On non-Windows, returns empty dict to avoid TypeError.
    """
    if IS_WINDOWS:
        return {"creationflags": WINDOWS_CREATION_FLAGS}
    return {}


def get_candidate_script_directories() -> list[str]:
    """
    Returns an ordered list of candidate directories where Python CLI scripts
    or native binaries may reside on Windows.
    """
    dirs: list[str] = []

    # 1. Project local bin directory
    if os.path.isdir(PROJECT_BIN_DIR):
        dirs.append(PROJECT_BIN_DIR)
        sub_ffmpeg = os.path.join(PROJECT_BIN_DIR, "ffmpeg", "bin")
        if os.path.isdir(sub_ffmpeg):
            dirs.append(sub_ffmpeg)

    # 2. Python sysconfig scripts (User AppData & System)
    try:
        nt_user_scripts = sysconfig.get_path("scripts", "nt_user")
        if nt_user_scripts and os.path.isdir(nt_user_scripts) and nt_user_scripts not in dirs:
            dirs.append(nt_user_scripts)
    except Exception:
        pass

    try:
        sys_scripts = sysconfig.get_path("scripts")
        if sys_scripts and os.path.isdir(sys_scripts) and sys_scripts not in dirs:
            dirs.append(sys_scripts)
    except Exception:
        pass

    # 3. Standard Windows Python prefix scripts
    prefix_scripts = os.path.join(sys.prefix, "Scripts")
    if os.path.isdir(prefix_scripts) and prefix_scripts not in dirs:
        dirs.append(prefix_scripts)

    base_scripts = os.path.join(sys.base_prefix, "Scripts")
    if os.path.isdir(base_scripts) and base_scripts not in dirs:
        dirs.append(base_scripts)

    # 4. User Base Scripts
    try:
        import site
        if hasattr(site, "USER_BASE") and site.USER_BASE:
            ub_scripts = os.path.join(
                site.USER_BASE,
                f"Python{sys.version_info.major}{sys.version_info.minor}",
                "Scripts",
            )
            if os.path.isdir(ub_scripts) and ub_scripts not in dirs:
                dirs.append(ub_scripts)
    except Exception:
        pass

    # 5. WinGet & Chocolatey well-known locations
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        winget_links = os.path.join(local_app_data, "Microsoft", "WinGet", "Links")
        if os.path.isdir(winget_links) and winget_links not in dirs:
            dirs.append(winget_links)

        # WinGet package search for FFmpeg
        winget_pkgs = os.path.join(local_app_data, "Microsoft", "WinGet", "Packages")
        if os.path.isdir(winget_pkgs):
            try:
                for entry in os.listdir(winget_pkgs):
                    if "FFmpeg" in entry or "ffmpeg" in entry:
                        entry_dir = os.path.join(winget_pkgs, entry)
                        if os.path.isdir(entry_dir):
                            for sub in os.listdir(entry_dir):
                                sub_path = os.path.join(entry_dir, sub)
                                if os.path.isdir(sub_path):
                                    sub_bin = os.path.join(sub_path, "bin")
                                    if os.path.isdir(sub_bin) and sub_bin not in dirs:
                                        dirs.append(sub_bin)
                                    if sub.lower() == "bin" and sub_path not in dirs:
                                        dirs.append(sub_path)
                        candidate = os.path.join(winget_pkgs, entry, "ffmpeg", "bin")
                        if os.path.isdir(candidate) and candidate not in dirs:
                            dirs.append(candidate)
                        candidate2 = os.path.join(winget_pkgs, entry, "bin")
                        if os.path.isdir(candidate2) and candidate2 not in dirs:
                            dirs.append(candidate2)
            except Exception:
                pass

    # 6. Windows Registry User & System Environment Path
    if IS_WINDOWS:
        try:
            import winreg

            reg_targets = [
                (winreg.HKEY_CURRENT_USER, "Environment"),
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
                ),
            ]
            for root_key, sub_key in reg_targets:
                try:
                    with winreg.OpenKey(root_key, sub_key) as k:
                        val, _ = winreg.QueryValueEx(k, "Path")
                        for p in val.split(";"):
                            expanded = os.path.expandvars(p.strip())
                            if expanded and os.path.isdir(expanded) and expanded not in dirs:
                                dirs.append(expanded)
                except Exception:
                    pass
        except Exception:
            pass

    choco_bin = r"C:\ProgramData\chocolatey\bin"
    if os.path.isdir(choco_bin) and choco_bin not in dirs:
        dirs.append(choco_bin)

    c_ffmpeg = r"C:\ffmpeg\bin"
    if os.path.isdir(c_ffmpeg) and c_ffmpeg not in dirs:
        dirs.append(c_ffmpeg)

    c_pf_ffmpeg = r"C:\Program Files\ffmpeg\bin"
    if os.path.isdir(c_pf_ffmpeg) and c_pf_ffmpeg not in dirs:
        dirs.append(c_pf_ffmpeg)

    return dirs


def resolve_tool(tool_name: str) -> list[str]:
    """
    Resolves the command invocation prefix for a CLI tool using a 5-tier strategy.

    Returns:
        A list of strings representing the command prefix.
        E.g. ['C:\\...\\yt-dlp.exe'] or [sys.executable, '-m', 'yt_dlp'].
    """
    clean_tool = tool_name.strip()

    # Tier 1: Check system/process PATH
    found = shutil.which(clean_tool)
    if found:
        return [found]

    if IS_WINDOWS and not clean_tool.lower().endswith(".exe"):
        found = shutil.which(f"{clean_tool}.exe")
        if found:
            return [found]

    # Tier 2: Check known Scripts & local bin directories
    for d in get_candidate_script_directories():
        candidate_exe = os.path.join(
            d, f"{clean_tool}.exe" if IS_WINDOWS else clean_tool
        )
        if os.path.isfile(candidate_exe):
            return [candidate_exe]

    # Tier 3: Python module invocation fallback (for Python tools)
    module_name = PYTHON_MODULE_MAP.get(clean_tool) or clean_tool.replace("-", "_")
    if module_name:
        try:
            spec = importlib.util.find_spec(module_name)
            if spec is not None:
                return [sys.executable, "-m", module_name]
        except Exception:
            pass

    # Tier 4: For native tools (ffmpeg / ffprobe), raise actionable error
    if clean_tool in ("ffmpeg", "ffprobe"):
        raise ToolNotFoundError(
            f"'{clean_tool}' executable was not found in PATH or standard directories.\n"
            "To install FFmpeg on Windows, run:\n"
            "  winget install --id Gyan.FFmpeg -e\n"
            f"Or place '{clean_tool}.exe' directly in '{PROJECT_BIN_DIR}'."
        )

    # Tier 5: Python tool missing
    install_hint = (
        f"python -m pip install {clean_tool}"
        if module_name
        else f"install {clean_tool}"
    )
    raise ToolNotFoundError(
        f"'{clean_tool}' is not installed.\n"
        f"Install it by running:\n  {install_hint}"
    )


def get_subprocess_env() -> dict[str, str]:
    """
    Builds the environment dictionary for child processes:
    1. Prepend all candidate script/bin directories to PATH so child processes
       (e.g. yt-dlp spawning ffmpeg) discover dependencies automatically.
    2. Enforce UTF-8 output encoding to avoid Windows charmap encoding crashes.
    """
    env = os.environ.copy()
    candidate_dirs = get_candidate_script_directories()

    current_path = env.get("PATH", "")
    existing_paths = current_path.split(os.pathsep) if current_path else []
    new_paths = [d for d in candidate_dirs if d not in existing_paths]

    if new_paths:
        env["PATH"] = os.pathsep.join(new_paths) + os.pathsep + current_path
        if IS_WINDOWS and "Path" in env:
            env["Path"] = env["PATH"]

    # Enforce UTF-8 for Python child tools
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def extract_downloaded_filename(
    stdout: str, target_dir: str, before_files: Optional[set[str]] = None
) -> Optional[str]:
    """
    Extracts the final downloaded filename using stage-prioritized regex
    backed by filesystem snapshot differential.
    """
    lines = stdout.splitlines()

    # Priority 1: Audio Extraction Destination (Final for -x --audio-format mp3)
    for line in reversed(lines):
        m = re.search(r"\[ExtractAudio\]\s+Destination:\s+(.+)", line, re.IGNORECASE)
        if m:
            clean = m.group(1).strip().strip('"')
            return os.path.basename(clean)

    # Priority 2: Merger Destination (Final for merged video)
    for line in reversed(lines):
        m = re.search(
            r'\[Merger\]\s+Merging formats into\s+"?([^"\r\n]+)"?',
            line,
            re.IGNORECASE,
        )
        if m:
            clean = m.group(1).strip().strip('"')
            return os.path.basename(clean)

    # Priority 3: MoveFiles Destination
    for line in reversed(lines):
        m = re.search(
            r'\[MoveFiles\]\s+Moving file .+ to\s+"?([^"\r\n]+)"?',
            line,
            re.IGNORECASE,
        )
        if m:
            clean = m.group(1).strip().strip('"')
            return os.path.basename(clean)

    # Priority 4: Direct Download Destination or already downloaded
    for line in reversed(lines):
        m_dest = re.search(
            r"\[download\]\s+Destination:\s+(.+)", line, re.IGNORECASE
        )
        if m_dest:
            clean = m_dest.group(1).strip().strip('"')
            return os.path.basename(clean)
        m_done = re.search(
            r"\[download\]\s+(.+)\s+has already been downloaded",
            line,
            re.IGNORECASE,
        )
        if m_done:
            clean = m_done.group(1).strip().strip('"')
            return os.path.basename(clean)

    # Priority 5: gallery-dl printed file paths
    for line in reversed(lines):
        clean = line.strip().lstrip("#").strip()
        if clean and os.path.dirname(clean) and os.path.splitext(clean)[1]:
            try:
                if os.path.commonpath(
                    [os.path.abspath(target_dir), os.path.abspath(clean)]
                ) == os.path.abspath(target_dir):
                    return os.path.basename(clean)
            except Exception:
                pass

    # Priority 6: Filesystem Differential Snapshot
    if before_files is not None and os.path.isdir(target_dir):
        try:
            after_files = set(os.listdir(target_dir))
            new_files = [
                f
                for f in (after_files - before_files)
                if not f.endswith((".part", ".ytdl", ".temp", ".tmp"))
            ]
            if len(new_files) == 1:
                return new_files[0]
            elif len(new_files) > 1:
                return f"{len(new_files)} files ({new_files[0]}, ...)"
        except Exception:
            pass

    return None


def extract_error_details(stderr: str, stdout: str) -> str:
    """
    Parses subprocess output to extract clean, actionable error messages,
    filtering out non-fatal warnings and ANSI color escapes.
    """
    ansi_cleaner = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    clean_stderr = ansi_cleaner.sub("", stderr)

    err_lines = [
        line.strip() for line in clean_stderr.splitlines() if line.strip()
    ]

    # 1. Filter out warnings, locate genuine ERROR: lines
    explicit_errors = []
    for line in err_lines:
        if line.upper().startswith("WARNING:"):
            continue
        if re.search(r"(?:^ERROR:|^\[error\]|HttpError:)", line, re.IGNORECASE):
            cleaned = re.sub(
                r"^(?:ERROR:\s*|\[error\]\s*)", "", line, flags=re.IGNORECASE
            )
            explicit_errors.append(cleaned.strip())

    if explicit_errors:
        return " | ".join(explicit_errors)[:300]

    # 2. Fallback to last non-warning line of stderr
    for line in reversed(err_lines):
        if not line.upper().startswith("WARNING:"):
            return line[:300]

    # 3. Fallback to last non-empty line of stdout
    clean_stdout = ansi_cleaner.sub("", stdout)
    out_lines = [
        line.strip() for line in clean_stdout.splitlines() if line.strip()
    ]
    if out_lines:
        return out_lines[-1][:300]

    return "Process terminated with non-zero exit code"


def run_command_stealth(
    cmd: list[str],
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Tuple[int, str, str]:
    """
    Executes a command stealthily with CREATE_NO_WINDOW and BELOW_NORMAL priority.
    Captures stdout and stderr with UTF-8 decoding and surrogate replacement.

    Returns:
        (returncode, stdout_str, stderr_str)
    """
    kwargs = get_subprocess_kwargs()
    env = get_subprocess_env()

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kwargs,
    )

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        stderr = (
            f"Process timed out after {timeout} seconds.\n" + (stderr or "")
        )
        return -1, stdout or "", stderr

    return proc.returncode, stdout or "", stderr or ""


def execute_download_job(
    job_id: str,
    url: str,
    target_dir: str,
    format_type: str = "video",
) -> Optional[str]:
    """
    Subprocess runner with output capture, real-time progress parsing, and error logging.
    Executes the download command using stealth flags and updates QueueManager progress.

    Returns:
        The extracted downloaded filename on success, or raises RuntimeError on failure.
    """
    from core.routing import build_download_command

    norm_dir = os.path.normpath(os.path.abspath(target_dir))
    os.makedirs(norm_dir, exist_ok=True)

    before_files: set[str] = set()
    try:
        before_files = set(os.listdir(norm_dir))
    except Exception:
        pass

    platform, cmd = build_download_command(url, norm_dir, format_type)
    kwargs = get_subprocess_kwargs()
    env = get_subprocess_env()

    logger.info("Executing download job [%s]: platform=%s cmd=%s", job_id, platform, " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        cwd=norm_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kwargs,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    progress_regex = re.compile(
        r"\[download\]\s+([0-9.]+)%\s+of\s+~?([0-9.]+[A-Za-z]+)\s+at\s+([0-9.]+[A-Za-z]+/s)\s+ETA\s+([0-9:]+)",
        re.IGNORECASE,
    )
    simple_progress = re.compile(r"\[download\]\s+([0-9.]+)%", re.IGNORECASE)

    try:
        # Lazy import of queue manager to avoid circular import
        from core.queue_manager import get_queue_manager
        qm = get_queue_manager()
    except Exception:
        qm = None

    if proc.stdout is not None:
        for line in iter(proc.stdout.readline, ""):
            stdout_lines.append(line)
            if qm is not None:
                # Progress parsing
                m = progress_regex.search(line)
                if m:
                    try:
                        pct = float(m.group(1))
                        speed = m.group(3)
                        eta = m.group(4)
                        qm.update_job_progress(job_id, progress=pct, speed=speed, eta=eta)
                    except Exception:
                        pass
                else:
                    m2 = simple_progress.search(line)
                    if m2:
                        try:
                            pct = float(m2.group(1))
                            qm.update_job_progress(job_id, progress=pct)
                        except Exception:
                            pass

    stderr_output = ""
    if proc.stderr is not None:
        stderr_output = proc.stderr.read()
        stderr_lines.append(stderr_output)

    try:
        proc.wait(timeout=600)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise RuntimeError("Download job timed out (exceeded 600 seconds limit)")

    full_stdout = "".join(stdout_lines)
    full_stderr = "".join(stderr_lines)

    if proc.returncode != 0:
        error_msg = extract_error_details(full_stderr, full_stdout)
        logger.error("Job [%s] failed with exit code %s: %s", job_id, proc.returncode, error_msg)
        raise RuntimeError(error_msg)

    filename = extract_downloaded_filename(full_stdout, norm_dir, before_files)
    logger.info("Job [%s] completed successfully. Filename: %s", job_id, filename)
    return filename


# Re-export build_download_command for convenience
from core.routing import build_download_command  # noqa: E402
