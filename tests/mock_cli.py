"""
tests/mock_cli.py — Mock CLI Subprocess Interceptor for AssetDrop (v2.0).

Simulates yt-dlp, gallery-dl, and ffmpeg executions offline:
- Validates that Windows creationflags equal 0x08004000 (CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS).
- Generates realistic dummy media files in destination directories.
- Returns stdout progress telemetry and exit code 0 (or configured error codes).
- Provides context managers and decorators for clean test isolation.
"""

from __future__ import annotations

import io
import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import patch

# Windows Creationflags: CREATE_NO_WINDOW (0x08000000) | BELOW_NORMAL_PRIORITY_CLASS (0x00004000)
EXPECTED_WINDOWS_CREATIONFLAGS = 0x08004000  # 134234112


class MockProcess:
    """Mock implementation of subprocess.Popen object."""

    def __init__(
        self,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ):
        self.returncode = returncode
        self._stdout_str = stdout
        self._stderr_str = stderr
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)

    def communicate(self, timeout: Optional[float] = None) -> tuple[str, str]:
        return self._stdout_str, self._stderr_str

    def wait(self, timeout: Optional[float] = None) -> int:
        return self.returncode

    def poll(self) -> Optional[int]:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


class MockCLIInterceptor:
    """
    Subprocess interceptor that validates flags and simulates CLI tool execution.
    """

    def __init__(
        self,
        assert_creationflags: bool = True,
        simulate_failure: bool = False,
        failure_code: int = 1,
        failure_stderr: str = "ERROR: [mock] Video unavailable or network failure",
        custom_filename: Optional[str] = None,
    ):
        self.assert_creationflags = assert_creationflags
        self.simulate_failure = simulate_failure
        self.failure_code = failure_code
        self.failure_stderr = failure_stderr
        self.custom_filename = custom_filename
        self.invocations: List[Dict[str, Any]] = []
        self.created_files: List[str] = []

    def __call__(self, *args, **kwargs) -> MockProcess:
        # Extract command line
        cmd = args[0] if args else kwargs.get("args")
        if isinstance(cmd, str):
            cmd_list = cmd.split()
        elif isinstance(cmd, (list, tuple)):
            cmd_list = list(cmd)
        else:
            cmd_list = []

        cwd = kwargs.get("cwd") or os.getcwd()
        creationflags = kwargs.get("creationflags", 0)

        # Validate Windows stealth flags on Windows hosts
        if sys.platform == "win32" and self.assert_creationflags:
            if creationflags != EXPECTED_WINDOWS_CREATIONFLAGS:
                raise AssertionError(
                    f"Subprocess invoked with invalid creationflags: {creationflags:#x} "
                    f"({creationflags}). Expected 0x08004000 (134234112)."
                )

        invocation_record: Dict[str, Any] = {
            "cmd": cmd_list,
            "cwd": cwd,
            "creationflags": creationflags,
            "kwargs": kwargs,
            "simulated_file": None,
        }

        # Simulated failure branch
        if self.simulate_failure:
            self.invocations.append(invocation_record)
            return MockProcess(
                returncode=self.failure_code,
                stdout="",
                stderr=self.failure_stderr,
            )

        # Simulated success branch: determine generated file type
        cmd_str = " ".join(cmd_list)
        is_gallery_dl = any("gallery-dl" in arg for arg in cmd_list)
        is_audio = "-x" in cmd_list or "--audio-format" in cmd_list

        if self.custom_filename:
            filename = self.custom_filename
        elif is_gallery_dl:
            filename = "Simulated_Pinterest_Pin_847291.jpg"
        elif is_audio:
            filename = "Simulated Audio Track [aud_91823].mp3"
        else:
            filename = "Simulated Video Asset [vid_58392].mp4"

        # Create simulated file on disk in target folder
        norm_cwd = os.path.normpath(os.path.abspath(cwd))
        os.makedirs(norm_cwd, exist_ok=True)
        file_path = os.path.join(norm_cwd, filename)
        try:
            with open(file_path, "wb") as f:
                f.write(b"ASSETDROP_SIMULATED_MEDIA_PAYLOAD\x00\x00\x00\x01")
            self.created_files.append(file_path)
            invocation_record["simulated_file"] = file_path
        except Exception:
            pass

        # Build realistic stdout progress output
        stdout_output = (
            f"[download] Destination: {filename}\n"
            f"[download]   0.0% of ~10.50MiB at 5.20MiB/s ETA 00:02\n"
            f"[download]  50.0% of ~10.50MiB at 10.40MiB/s ETA 00:01\n"
            f"[download] 100% of 10.50MiB at 12.00MiB/s ETA 00:00\n"
            f"[download] 100% of 10.50MiB in 00:01\n"
            f'[Merger] Merging formats into "{filename}"\n'
        )

        self.invocations.append(invocation_record)
        return MockProcess(
            returncode=0,
            stdout=stdout_output,
            stderr="",
        )


class patch_subprocess_cli:
    """
    Context manager that intercepts subprocess.Popen across the AssetDrop application.
    """

    def __init__(self, interceptor: Optional[MockCLIInterceptor] = None):
        self.interceptor = interceptor or MockCLIInterceptor()
        self._patcher: Optional[Any] = None

    def __enter__(self) -> MockCLIInterceptor:
        self._patcher = patch("subprocess.Popen", side_effect=self.interceptor)
        self._patcher.start()
        return self.interceptor

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._patcher:
            self._patcher.stop()


def simulated_worker_func(job_id: str, url: str, target_dir: str, format_type: str) -> str:
    """
    Direct in-process mock worker that can be bound to QueueManager._worker_func
    for rapid in-memory pipeline verification.
    """
    norm_dir = os.path.normpath(os.path.abspath(target_dir))
    os.makedirs(norm_dir, exist_ok=True)

    if format_type.lower() in ("audio", "mp3"):
        filename = f"Simulated_Track_{job_id[:8]}.mp3"
    elif "pinterest" in url.lower() or "pin.it" in url.lower():
        filename = f"Simulated_Pin_{job_id[:8]}.jpg"
    else:
        filename = f"Simulated_Video_{job_id[:8]}.mp4"

    file_path = os.path.join(norm_dir, filename)
    with open(file_path, "wb") as f:
        f.write(b"SIMULATED_WORKER_PAYLOAD")

    return filename
