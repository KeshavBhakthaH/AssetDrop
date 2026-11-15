"""
test_env.py — Pre-flight Environment Diagnostic & Directory Initialization Helper.

Verifies runtime prerequisites:
- Python 3.10+
- FFmpeg (stream muxing and 320kbps MP3 extraction)
- yt-dlp (video/audio ingestion engine)
- gallery-dl (Pinterest ingestion engine)

Reads config.json and automatically creates missing preset directories on disk.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def check_python_version() -> tuple[bool, str]:
    v = sys.version_info
    ver_str = f"{v.major}.{v.minor}.{v.micro}"
    passed = v.major == 3 and v.minor >= 10
    return passed, ver_str


def check_cli_tool(tool_name: str, module_name: str | None = None) -> tuple[bool, str]:
    # 1. Direct shutil.which check in PATH
    path = shutil.which(tool_name)
    if path:
        try:
            res = subprocess.run(
                [path, "-version" if tool_name == "ffmpeg" else "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            out = res.stdout.strip().splitlines()[0] if res.stdout else "Available"
            return True, f"{tool_name} ({out[:30]})"
        except Exception:
            return True, path

    # 2. Check Python Scripts folder fallback
    scripts_dir = Path(sys.executable).parent / "Scripts"
    candidate = scripts_dir / f"{tool_name}.exe"
    if candidate.exists():
        return True, f"Found in Scripts: {candidate}"

    # 3. Check Python module fallback
    if module_name:
        try:
            res = subprocess.run(
                [sys.executable, "-m", module_name, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                ver = res.stdout.strip().splitlines()[0] if res.stdout else "Module available"
                return True, f"Python module ({ver[:30]})"
        except Exception:
            pass

    return False, "Not found"


def initialize_directories() -> list[tuple[str, str, str]]:
    config_path = Path(__file__).parent / "config.json"
    results = []
    if not config_path.exists():
        return [("config.json", str(config_path), "File missing")]

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        presets = cfg.get("presets", {})
        for label, folder in presets.items():
            try:
                os.makedirs(folder, exist_ok=True)
                status = "OK (Directory created/ready)"
            except Exception as e:
                status = f"Failed: {e}"
            results.append((label, folder, status))
    except Exception as e:
        results.append(("Error reading config", str(config_path), str(e)))

    return results


def main():
    print("=" * 75)
    print("  ASSETDROP 2.0 — PRE-FLIGHT SYSTEM DIAGNOSTIC")
    print("=" * 75)

    py_ok, py_ver = check_python_version()
    ffmpeg_ok, ffmpeg_info = check_cli_tool("ffmpeg")
    ytdlp_ok, ytdlp_info = check_cli_tool("yt-dlp", "yt_dlp")
    gallery_ok, gallery_info = check_cli_tool("gallery-dl", "gallery_dl")

    checks = [
        ("Python Runtime (>=3.10)", py_ok, py_ver),
        ("FFmpeg (Muxing / MP3)", ffmpeg_ok, ffmpeg_info),
        ("yt-dlp (Ingestion)", ytdlp_ok, ytdlp_info),
        ("gallery-dl (Pinterest)", gallery_ok, gallery_info),
    ]

    print(f"{'Component':<28} | {'Status':<10} | {'Details'}")
    print("-" * 75)
    all_passed = True
    for name, ok, details in checks:
        status_str = "[ PASS ]" if ok else "[ FAIL ]"
        if not ok:
            all_passed = False
        print(f"{name:<28} | {status_str:<10} | {details}")

    print("-" * 75)
    print("\nTarget Preset Folders Initialization (config.json):")
    print("-" * 75)
    dir_results = initialize_directories()
    for label, path, status in dir_results:
        print(f"  * {label:<22} -> {path:<25} [{status}]")

    print("=" * 75)
    if all_passed:
        print("  SYSTEM READY: All prerequisites satisfied.")
    else:
        print("  WARNING: Some prerequisites are missing. Ingestion may fail.")
    print("=" * 75)


if __name__ == "__main__":
    main()
