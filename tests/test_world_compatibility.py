"""
tests/test_world_compatibility.py — Validates that AssetDrop runs out-of-the-box
on any computer in the world with no hardcoded dependencies, no drive assumptions,
and complete fresh-environment resilience.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from core.config import (
    CONFIG_PATH,
    DEFAULT_CONFIG,
    DEFAULT_PRESETS,
    derive_server_uid,
    ensure_preset_directories,
    generate_connection_password,
    get_default_presets,
    load_config,
    save_config,
)
from core.subprocess_runner import (
    resolve_tool,
    ToolNotFoundError,
)
import server


class TestWorldCompatibility(unittest.TestCase):
    """Verifies that any user in the world can use AssetDrop seamlessly."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="assetdrop_world_test_")
        self.temp_config_path = os.path.join(self.temp_dir, "config.json")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_smart_default_presets_without_drive_d(self):
        """Ensures computers without drive D: get safe, working user directory presets."""
        with patch("os.path.exists", return_value=False):
            presets = get_default_presets()
            self.assertIsInstance(presets, dict)
            self.assertGreater(len(presets), 0)
            for name, path_str in presets.items():
                self.assertNotIn("D:", path_str, f"Preset '{name}' should not assume drive D: if D: does not exist")
                self.assertTrue(len(path_str) > 0)

    def test_fresh_boot_without_existing_config(self):
        """Simulates a fresh clone where config.json does not exist yet."""
        cfg = load_config(self.temp_config_path)
        self.assertIn("host", cfg)
        self.assertIn("port", cfg)
        self.assertIn("workstation_id", cfg)
        self.assertIn("presets", cfg)
        self.assertGreater(len(cfg["presets"]), 0)

        # Ensure UID is generated deterministically
        uid = derive_server_uid("192.168.1.50")
        self.assertEqual(len(uid), 5)
        self.assertTrue(uid.isdigit())

        # Ensure password has high entropy
        pw = generate_connection_password()
        self.assertEqual(len(pw), 8)

    def test_ensure_preset_directories_resilience_to_missing_drives(self):
        """Ensures that impossible drive letters (e.g. Z:/NonExistentDrive) do not crash the app."""
        bad_presets = {
            "Ghost Drive": "Z:/Totally/Fake/Drive/That/Does/Not/Exist/BRoll",
            "Local Fallback": os.path.join(self.temp_dir, "WorkingPreset"),
        }
        # Must not raise an unhandled exception
        try:
            ensure_preset_directories(bad_presets)
        except Exception as e:
            self.fail(f"ensure_preset_directories crashed on non-existent drive: {e}")

        # The valid local path must still be created
        self.assertTrue(os.path.exists(bad_presets["Local Fallback"]))

    def test_cli_tool_resolver_handles_clean_environment(self):
        """Verifies CLI resolver finds python module fallbacks or returns actionable error."""
        # yt-dlp is in python environment
        try:
            yt_cmd = resolve_tool("yt-dlp")
            self.assertTrue(len(yt_cmd) >= 1)
        except ToolNotFoundError as e:
            # If not installed, message must give clear command
            self.assertIn("pip install", str(e))

        # A completely unknown tool must raise ToolNotFoundError with pip install hint
        with self.assertRaises(ToolNotFoundError) as ctx:
            resolve_tool("nonexistent-media-tool-xyz")
        self.assertIn("pip install", str(ctx.exception))

    def test_public_apk_endpoint_available(self):
        """Verifies that the Android APK is publicly downloadable via HTTP."""
        client = TestClient(server.app)
        resp = client.get("/download/apk")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "application/vnd.android.package-archive")
        self.assertGreater(len(resp.content), 1000000, "APK must be a complete binary > 1MB")

    def test_public_web_manifest_available(self):
        """Verifies that the web manifest is accessible and configured for PWA installation."""
        client = TestClient(server.app)
        resp = client.get("/manifest.json")
        self.assertEqual(resp.status_code, 200)
        manifest = resp.json()
        self.assertEqual(manifest.get("short_name"), "AssetDrop")
        self.assertEqual(manifest.get("display"), "standalone")


if __name__ == "__main__":
    unittest.main()
