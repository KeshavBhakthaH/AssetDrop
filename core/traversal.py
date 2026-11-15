"""
core/traversal.py — Windows Drive Enumeration & Safe Filesystem Traversal.

Enumerates active Windows drives and traverses directories with safe attribute
filtering (ignoring hidden, system, and dot-folders) and graceful permission error handling.
"""

from __future__ import annotations

import logging
import os
import string
import sys
from typing import Any, Dict, List, Optional

logger = logging.getLogger("assetdrop.traversal")


def get_windows_drives() -> List[str]:
    """
    Returns a list of mounted, accessible Windows drive root paths (e.g. ['C:\\', 'D:\\']).
    On non-Windows systems, returns ['/'].
    """
    drives: List[str] = []

    if sys.platform == "win32":
        try:
            import ctypes

            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if (bitmask >> i) & 1:
                    drive_letter = chr(ord("A") + i)
                    drive_path = f"{drive_letter}:\\"
                    try:
                        if os.path.isdir(drive_path):
                            drives.append(drive_path)
                    except OSError:
                        pass
        except Exception as exc:
            logger.warning("GetLogicalDrives failed (%s), falling back to drive letter scan.", exc)
            for letter in string.ascii_uppercase:
                drive_path = f"{letter}:\\"
                try:
                    if os.path.isdir(drive_path):
                        drives.append(drive_path)
                except OSError:
                    pass
    else:
        drives.append("/")

    return drives


def browse_directory(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Safely traverses immediate subdirectories of a given filesystem path.

    Filtering & Security Rules:
    - Null-byte injection check.
    - Resolves empty path to primary drive root.
    - Handles Windows DOS drive semantics ('D:' -> 'D:\\').
    - Skips non-directory items.
    - Skips dot-files and Windows $ system directories (e.g. $Recycle.Bin, .git).
    - On Windows, filters FILE_ATTRIBUTE_HIDDEN (0x02) and FILE_ATTRIBUTE_SYSTEM (0x04).
    - Gracefully handles PermissionError and OSError without server exceptions.
    - Returns dual-key aliases ('folders' and 'subdirectories') and root-safe 'parent' (None for drive roots).
    """
    # 1. Fallback to default drive if path is empty
    if not path or not path.strip():
        drives = get_windows_drives()
        path = drives[0] if drives else ("C:\\" if sys.platform == "win32" else "/")

    clean_path = path.strip()

    # Prevent null-byte injection
    if "\x00" in clean_path:
        return {
            "current": clean_path,
            "parent": None,
            "folders": [],
            "subdirectories": [],
            "error": "Invalid path",
        }

    # 2. Windows DOS semantics: 'D:' -> 'D:\'
    if sys.platform == "win32" and len(clean_path) == 2 and clean_path[1] == ":":
        clean_path = clean_path.upper() + "\\"

    # 3. Path normalization
    norm_path = os.path.abspath(os.path.normpath(clean_path))
    if sys.platform == "win32" and len(norm_path) == 2 and norm_path[1] == ":":
        norm_path += "\\"

    # 4. Existence and directory validation
    if not os.path.exists(norm_path):
        return {
            "current": norm_path,
            "parent": None,
            "folders": [],
            "subdirectories": [],
            "error": "Directory not found",
        }

    if not os.path.isdir(norm_path):
        return {
            "current": norm_path,
            "parent": None,
            "folders": [],
            "subdirectories": [],
            "error": "Path is not a directory",
        }

    # 5. Parent directory resolution (Drive root or filesystem root has parent=None)
    parent_candidate = os.path.dirname(norm_path)
    if parent_candidate == norm_path:
        parent_path = None
    else:
        parent_path = parent_candidate

    # 6. Scandir with safe Win32 attribute inspection
    folder_names: List[str] = []
    try:
        with os.scandir(norm_path) as iterator:
            for entry in iterator:
                try:
                    # Skip dot-files and Windows $ system directories
                    if entry.name.startswith((".", "$")):
                        continue

                    # Win32 attribute inspection for hidden / system files
                    if sys.platform == "win32":
                        try:
                            attrs = getattr(entry.stat(), "st_file_attributes", 0)
                            if attrs & 0x00000002 or attrs & 0x00000004:
                                continue
                        except (PermissionError, OSError):
                            continue

                    if entry.is_dir(follow_symlinks=False):
                        folder_names.append(entry.name)
                except (PermissionError, OSError):
                    continue
    except PermissionError:
        return {
            "current": norm_path,
            "parent": parent_path,
            "folders": [],
            "subdirectories": [],
            "error": "Access denied",
        }
    except OSError as err:
        return {
            "current": norm_path,
            "parent": parent_path,
            "folders": [],
            "subdirectories": [],
            "error": f"OS Error: {str(err)}",
        }

    # Sort alphabetically (case-insensitive)
    sorted_folders = sorted(folder_names, key=str.lower)

    return {
        "current": norm_path,
        "parent": parent_path,
        "folders": sorted_folders,
        "subdirectories": sorted_folders,  # Dual alias
    }


def scan_subfolders(base_path: str, max_depth: int = 10, max_folders: int = 1000) -> List[str]:
    """
    Safely traverses and returns relative subdirectories inside base_path up to max_depth (default 10).
    Returns relative subfolder paths using forward slashes (e.g. ['B', 'C', 'B/sub', 'B/sub/deep']).
    Skips hidden, system, dot, and vendor directories.
    """
    if not base_path or not os.path.isdir(base_path):
        return []

    IGNORED_DIRS = {
        ".git", ".svn", ".hg", ".idea", ".vscode", "node_modules",
        "__pycache__", ".venv", "venv", "$recycle.bin", "system volume information",
        ".gemini", ".antigravity"
    }

    subfolders: List[str] = []
    base_norm = os.path.normpath(os.path.abspath(base_path))

    try:
        for root, dirs, _ in os.walk(base_norm, topdown=True):
            # Prune ignored and hidden directories in-place
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d.lower() not in IGNORED_DIRS
            ]
            rel = os.path.relpath(root, base_norm)
            if rel != ".":
                depth = len(rel.replace("\\", "/").split("/"))
                if depth > max_depth:
                    dirs.clear()
                    continue
                subfolders.append(rel.replace("\\", "/"))
                if len(subfolders) >= max_folders:
                    break
    except Exception as exc:
        logger.warning("Error scanning subfolders for %s: %s", base_path, exc)

    return sorted(subfolders, key=str.lower)
