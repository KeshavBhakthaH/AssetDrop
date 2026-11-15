"""
core/queue_manager.py — In-Memory Job Queue, ThreadPoolExecutor SLA & Telemetry.

Manages background media download jobs with sub-50ms ingestion SLA, bounded concurrency,
in-memory status tracking, and dual-key telemetry querying.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("assetdrop.queue")

DEFAULT_MAX_WORKERS = 2
DEFAULT_MAX_HISTORY = 50


@dataclass
class Job:
    """Represents a media ingestion job with live telemetry state."""

    id: str
    url: str
    platform: str
    format_type: str
    target_dir: str
    status: str = "queued"  # "queued" | "downloading" | "completed" | "failed"
    filename: Optional[str] = None
    title: Optional[str] = None
    file_size_bytes: int = 0
    progress: float = 0.0
    speed: Optional[str] = None
    eta: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def get_clean_title(self) -> str:
        """Derives a clean human-readable title from filename or platform."""
        if self.title and self.title.strip():
            return self.title.strip()
        if self.filename and self.filename.strip():
            name_without_ext, _ = os.path.splitext(self.filename.strip())
            # Strip trailing bracketed ID, e.g. "Title [dQw4w9WgXcQ]" -> "Title"
            cleaned = re.sub(r"\s*\[[^\]]+\]$", "", name_without_ext).strip()
            if cleaned:
                return cleaned
            return name_without_ext.strip()
        if self.platform and self.platform.strip():
            plat = self.platform.strip().capitalize()
            return f"{plat} Media"
        return "Media Download"

    def get_file_size_bytes(self) -> int:
        """Returns integer size of downloaded file on disk (or 0 if pending/active/not found)."""
        if self.status != "completed":
            return self.file_size_bytes if self.file_size_bytes > 0 else 0
        if self.file_size_bytes > 0:
            return self.file_size_bytes
        if self.filename and self.target_dir:
            full_path = os.path.normpath(os.path.join(self.target_dir, self.filename))
            if os.path.isfile(full_path):
                try:
                    sz = os.path.getsize(full_path)
                    self.file_size_bytes = sz
                    return sz
                except OSError:
                    pass
        return 0

    def get_file_size_str(self) -> str:
        """Returns formatted size string (e.g. '45.2 MB', '1.2 GB', or '--' if unknown)."""
        bytes_val = self.get_file_size_bytes()
        if bytes_val <= 0:
            return "--"
        if bytes_val < 1024:
            return f"{bytes_val} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.1f} KB"
        elif bytes_val < 1024 * 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.1f} MB"
        else:
            return f"{bytes_val / (1024 * 1024 * 1024):.1f} GB"

    def get_format_label(self) -> str:
        """Returns 'MP3' for audio, 'MP4' for video."""
        if str(self.format_type).lower() in ("audio", "mp3"):
            return "MP3"
        return "MP4"

    def to_dict(self) -> dict[str, Any]:
        """Serializes Job state with dual key aliases for client compatibility."""
        clean_title = self.get_clean_title()
        size_bytes = self.get_file_size_bytes()
        size_str = self.get_file_size_str()
        format_label = self.get_format_label()
        filepath = os.path.normpath(os.path.join(self.target_dir, self.filename)) if self.filename else None

        return {
            "id": self.id,
            "url": self.url,
            "platform": self.platform,
            "format_type": self.format_type,
            "format_label": format_label,
            "title": clean_title,
            "target_dir": self.target_dir,
            "target_folder": self.target_dir,  # Dual alias
            "status": self.status,
            "filename": self.filename,
            "filepath": filepath,
            "file_size_bytes": size_bytes,
            "size_bytes": size_bytes,  # Dual alias
            "file_size_str": size_str,
            "size_formatted": size_str,  # Dual alias
            "progress": round(self.progress, 1),
            "speed": self.speed,
            "eta": self.eta,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class QueueManager:
    """
    Thread-safe media ingestion job manager.
    Guarantees sub-50ms ingestion response SLA by dispatching downloads
    to a bounded internal ThreadPoolExecutor.
    """

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        max_history: int = DEFAULT_MAX_HISTORY,
        worker_func: Optional[Callable[[str, str, str, str], Any]] = None,
    ) -> None:
        self._max_workers = max_workers
        self._max_history = max_history
        self._worker_func = worker_func
        self._lock = threading.RLock()
        self._active: Dict[str, Job] = {}
        self._completed: deque[Job] = deque(maxlen=max_history)
        self._failed: deque[Job] = deque(maxlen=max_history)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="assetdrop_worker",
        )

    def enqueue_job(
        self,
        url: str,
        target_dir: str,
        format_type: str = "video",
        platform: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> Job:
        """
        Instantly registers a download job and submits it for background execution.
        Execution duration is < 1ms, guaranteeing sub-50ms response SLA.
        """
        clean_id = job_id or str(uuid.uuid4())
        clean_url = url.strip() if url else ""

        if not platform:
            from core.routing import detect_platform
            detected_platform = detect_platform(clean_url)
        else:
            detected_platform = platform

        job = Job(
            id=clean_id,
            url=clean_url,
            platform=detected_platform,
            format_type=format_type,
            target_dir=target_dir,
            status="queued",
            created_at=time.time(),
        )

        with self._lock:
            self._active[job.id] = job

        logger.info("Enqueued job [%s] for %s (%s)", job.id, job.url, job.platform)

        # Dispatch execution asynchronously to the worker pool
        self._executor.submit(self._worker_wrapper, job.id)
        return job

    def _worker_wrapper(self, job_id: str) -> None:
        """Internal execution wrapper executing on thread pool worker thread."""
        with self._lock:
            job = self._active.get(job_id)
            if not job:
                return
            job.status = "downloading"
            job.started_at = time.time()

        try:
            if self._worker_func is not None:
                result = self._worker_func(job.id, job.url, job.target_dir, job.format_type)
            else:
                from core.subprocess_runner import execute_download_job

                result = execute_download_job(
                    job_id=job.id,
                    url=job.url,
                    target_dir=job.target_dir,
                    format_type=job.format_type,
                )
            filename = result if isinstance(result, str) else job.filename
            self.complete_job(job_id, filename=filename)
        except Exception as exc:
            logger.error("Job execution exception for [%s]: %s", job_id, exc)
            self.fail_job(job_id, error=str(exc))

    def update_job_progress(
        self,
        job_id: str,
        progress: float,
        speed: Optional[str] = None,
        eta: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> None:
        """Thread-safe update of live progress telemetry from subprocess streams."""
        with self._lock:
            job = self._active.get(job_id)
            if job:
                job.progress = max(0.0, min(100.0, progress))
                if speed:
                    job.speed = speed
                if eta:
                    job.eta = eta
                if filename:
                    job.filename = filename

    def complete_job(self, job_id: str, filename: Optional[str] = None) -> None:
        """Marks an active job as completed and transitions it to history."""
        # Pre-resolve target directory and filename to perform file stat outside lock
        target_dir = None
        fname = filename
        with self._lock:
            job_ref = self._active.get(job_id)
            if job_ref:
                target_dir = job_ref.target_dir
                if not fname:
                    fname = job_ref.filename

        file_size: Optional[int] = None
        if fname and target_dir:
            fpath = os.path.normpath(os.path.join(target_dir, fname))
            if os.path.isfile(fpath):
                try:
                    file_size = os.path.getsize(fpath)
                except OSError:
                    pass

        with self._lock:
            job = self._active.pop(job_id, None)
            if job:
                job.status = "completed"
                job.progress = 100.0
                if filename:
                    job.filename = filename
                job.completed_at = time.time()
                if file_size is not None:
                    job.file_size_bytes = file_size
                self._completed.appendleft(job)
                logger.info("Job [%s] marked completed (filename=%s)", job_id, job.filename)

    def fail_job(self, job_id: str, error: str) -> None:
        """Marks an active job as failed, stores error telemetry, and transitions to history."""
        with self._lock:
            job = self._active.pop(job_id, None)
            if job:
                job.status = "failed"
                job.error = error
                job.completed_at = time.time()
                self._failed.appendleft(job)
                logger.warning("Job [%s] marked failed: %s", job_id, error)

    def get_job(self, job_id: str) -> Optional[Job]:
        """Look up any job across active, completed, or failed collections."""
        with self._lock:
            if job_id in self._active:
                return self._active[job_id]
            for j in self._completed:
                if j.id == job_id:
                    return j
            for j in self._failed:
                if j.id == job_id:
                    return j
        return None

    def get_status(self) -> Dict[str, Any]:
        """
        Returns snapshot telemetry for all active and recently completed/failed jobs.
        Includes dual aliases ('recent' for 'completed', 'errors' for 'failed').
        """
        with self._lock:
            active_list = [j.to_dict() for j in self._active.values()]
            completed_list = [j.to_dict() for j in self._completed]
            failed_list = [j.to_dict() for j in self._failed]

        all_transfers = active_list + completed_list + failed_list

        return {
            "transfers": all_transfers,
            "active": active_list,
            "completed": completed_list,
            "failed": failed_list,
            "recent": completed_list,  # PROJECT.md contract alias
            "errors": failed_list,  # PROJECT.md contract alias
        }

    def clear_history(self) -> None:
        """Clears completed and failed history buffer."""
        with self._lock:
            self._completed.clear()
            self._failed.clear()

    def shutdown(self, wait: bool = False, cancel_futures: bool = True) -> None:
        """Shuts down background executor pool."""
        try:
            self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
        except TypeError:
            self._executor.shutdown(wait=wait)


# Module-level singleton
_queue_manager_instance: Optional[QueueManager] = None
_instance_lock = threading.Lock()


def get_queue_manager() -> QueueManager:
    """Returns the process singleton instance of QueueManager."""
    global _queue_manager_instance
    if _queue_manager_instance is None:
        with _instance_lock:
            if _queue_manager_instance is None:
                _queue_manager_instance = QueueManager()
    return _queue_manager_instance


def enqueue_job(url: str, target_dir: str, format_type: str = "video") -> Job:
    """Convenience module function conforming to PROJECT.md interface."""
    return get_queue_manager().enqueue_job(url, target_dir, format_type)


def get_status() -> Dict[str, Any]:
    """Convenience module function conforming to PROJECT.md interface."""
    return get_queue_manager().get_status()
