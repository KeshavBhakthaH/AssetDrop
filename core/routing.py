"""
core/routing.py — Media Platform Detection & Command Construction.

Detects media hosting platform from URL and constructs the exact CLI command list
according to the AssetDrop platform routing matrix and filename truncation specification.
"""

from __future__ import annotations

import os
import re
from typing import Optional, Tuple

PLATFORM_PATTERNS = {
    "youtube": re.compile(
        r"^(https?://)?([a-zA-Z0-9-]+\.)?(youtube\.com|youtu\.be)/",
        re.IGNORECASE,
    ),
    "instagram": re.compile(
        r"^(https?://)?([a-zA-Z0-9-]+\.)?(instagram\.com|instagr\.am)/",
        re.IGNORECASE,
    ),
    "tiktok": re.compile(
        r"^(https?://)?([a-zA-Z0-9-]+\.)?tiktok\.com/",
        re.IGNORECASE,
    ),
    "pinterest": re.compile(
        r"^(https?://)?([a-zA-Z0-9-]+\.)?(pinterest\.(?:com|[a-z]{2,4}(?:\.[a-z]{2})?)|pin\.it)/",
        re.IGNORECASE,
    ),
    "twitter": re.compile(
        r"^(https?://)?([a-zA-Z0-9-]+\.)?(twitter\.com|x\.com)/",
        re.IGNORECASE,
    ),
}

DEFAULT_FILENAME_TEMPLATE = "%(title).80s [%(id)s].%(ext)s"


def detect_platform(url: str) -> str:
    """
    Classifies input media URL into supported platform identifier.

    Returns:
        'youtube', 'instagram', 'tiktok', 'pinterest', 'twitter', or 'generic'.
    """
    cleaned_url = url.strip() if url else ""
    for platform, pattern in PLATFORM_PATTERNS.items():
        if pattern.search(cleaned_url):
            return platform
    return "generic"


def build_download_command(
    url: str,
    target_dir: str,
    format_type: str = "video",
    custom_template: Optional[str] = None,
) -> Tuple[str, list[str]]:
    """
    Builds the exact CLI argument list for the requested URL, format, and destination directory.

    Args:
        url: The media URL to download.
        target_dir: Destination folder path on disk.
        format_type: Requested format ('video' or 'audio').
        custom_template: Optional custom yt-dlp output template (defaults to %(title).80s [%(id)s].%(ext)s).

    Returns:
        tuple[str, list[str]]: (platform_name, cmd_args_list)
    """
    from core.subprocess_runner import resolve_tool

    clean_url = url.strip() if url else ""
    platform = detect_platform(clean_url)
    normalized_dir = os.path.normpath(os.path.abspath(target_dir))
    outtmpl = custom_template or DEFAULT_FILENAME_TEMPLATE

    if platform == "youtube":
        tool = resolve_tool("yt-dlp")
        if format_type.lower() == "audio":
            # YouTube Audio: 320kbps MP3 extraction
            cmd = tool + [
                "-x",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "0",
                "-o",
                outtmpl,
                "--paths",
                f"home:{normalized_dir}",
                clean_url,
            ]
        else:
            # YouTube Video: Best video + best audio merged to MP4
            cmd = tool + [
                "-f",
                "bv*+ba/b",
                "--merge-output-format",
                "mp4",
                "-o",
                outtmpl,
                "--paths",
                f"home:{normalized_dir}",
                clean_url,
            ]
        return platform, cmd

    elif platform == "pinterest":
        # Pinterest: gallery-dl
        tool = resolve_tool("gallery-dl")
        cmd = tool + [
            "--dest",
            normalized_dir,
            clean_url,
        ]
        return platform, cmd

    else:
        # Instagram, TikTok, Twitter/X, and Generic platforms:
        # Direct Max Quality MP4 stream via yt-dlp
        tool = resolve_tool("yt-dlp")
        cmd = tool + [
            "-f",
            "bv*+ba/b",
            "--merge-output-format",
            "mp4",
            "-o",
            outtmpl,
            "--paths",
            f"home:{normalized_dir}",
            clean_url,
        ]
        return platform, cmd
