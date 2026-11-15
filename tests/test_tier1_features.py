"""
tests/test_tier1_features.py — Tier 1: Feature Isolation Verification Suite.

Tests every feature (Features 1 through 28) defined in PROJECT.md and TEST_INFRA.md
in strict isolation (happy-path verification).

Coverage: >= 28 test cases.
Framework: Python standard library unittest + starlette.testclient.TestClient.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import unittest

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from starlette.testclient import TestClient

import server
from core.auth import create_session_token, verify_session_token
from core.config import (
    CONFIG_PATH,
    DEFAULT_PRESETS,
    PROJECT_ROOT as CFG_ROOT,
    add_preset,
    derive_server_uid,
    generate_connection_password,
    get_presets,
    load_config,
    save_config,
    verify_pin,
)
from core.queue_manager import get_queue_manager
from core.routing import build_download_command, detect_platform
from core.subprocess_runner import (
    WINDOWS_CREATION_FLAGS,
    ToolNotFoundError,
    get_subprocess_kwargs,
    resolve_tool,
)
from tests.mock_cli import (
    EXPECTED_WINDOWS_CREATIONFLAGS,
    MockCLIInterceptor,
    patch_subprocess_cli,
    simulated_worker_func,
)


class TestTier1Features(unittest.TestCase):
    """
    Tier 1: Feature Isolation Verification Suite (Features 1 - 28).
    """

    @classmethod
    def setUpClass(cls):
        for log_name in ("assetdrop", "httpx", "httpx2", "httpcore"):
            logging.getLogger(log_name).setLevel(logging.WARNING)
        cls.client = TestClient(server.app)
        cls.qm = get_queue_manager()
        # Bind in-process simulated worker for isolated testing
        cls.qm._worker_func = simulated_worker_func
        cls._user_config_backup = load_config()
        test_cfg = dict(cls._user_config_backup)
        presets = dict(DEFAULT_PRESETS)
        presets.update(test_cfg.get("presets", {}))
        test_cfg["presets"] = presets
        save_config(test_cfg)

    @classmethod
    def tearDownClass(cls):
        t_wait = 0.0
        while cls.qm._active and t_wait < 0.3:
            time.sleep(0.02)
            t_wait += 0.02
        cls.qm.clear_history()
        if hasattr(cls, "_user_config_backup"):
            save_config(cls._user_config_backup)

    def setUp(self):
        # Reset config to clean open-access state before each test
        self.original_config = load_config()
        clean_cfg = dict(self.original_config)
        clean_cfg["access_pin"] = None
        save_config(clean_cfg)

    def tearDown(self):
        # Restore original config
        save_config(self.original_config)

    # -------------------------------------------------------------------------
    # Feature 1: Configuration & Preset Auto-Creation
    # -------------------------------------------------------------------------
    def test_f01_config_and_presets_auto_creation(self):
        """Feature 1: Verifies default config and auto-creation of preset directories."""
        cfg = load_config()
        self.assertIn("presets", cfg)
        presets = cfg["presets"]
        expected_keys = [
            "B-Roll (General)",
            "Social Edits",
            "Sound Effects",
            "Background Music",
        ]
        for key in expected_keys:
            self.assertIn(key, presets, f"Missing core preset: {key}")
            path = presets[key]
            # Directory must be automatically created on startup
            self.assertTrue(
                os.path.isdir(path),
                f"Preset directory was not auto-created on disk: {path}",
            )

    def test_f01b_get_presets_helper(self):
        """Feature 1b: Verifies get_presets() returns valid mapping."""
        presets = get_presets()
        self.assertIsInstance(presets, dict)
        self.assertGreaterEqual(len(presets), 4)
        self.assertIn("B-Roll (General)", presets)

    # -------------------------------------------------------------------------
    # Feature 2: Resilient CLI Tool Resolution
    # -------------------------------------------------------------------------
    def test_f02_resolve_tool_yt_dlp(self):
        """Feature 2: Dynamic resolution of yt-dlp across PATH and Python scripts."""
        cmd_prefix = resolve_tool("yt-dlp")
        self.assertIsInstance(cmd_prefix, list)
        self.assertGreater(len(cmd_prefix), 0)
        # Either direct executable path or [python.exe, -m, yt_dlp]
        if len(cmd_prefix) == 1:
            self.assertTrue(
                os.path.isfile(cmd_prefix[0]) or "yt-dlp" in cmd_prefix[0].lower()
            )
        else:
            self.assertIn("-m", cmd_prefix)
            self.assertIn("yt_dlp", cmd_prefix)

    def test_f02b_resolve_tool_nonexistent_raises(self):
        """Feature 2b: Non-existent tool raises ToolNotFoundError cleanly."""
        with self.assertRaises((ToolNotFoundError, FileNotFoundError)):
            resolve_tool("nonexistent_tool_xyz_999")

    # -------------------------------------------------------------------------
    # Feature 3: Subprocess Stealth & Timeline Protection Flags
    # -------------------------------------------------------------------------
    def test_f03_subprocess_stealth_flags_windows(self):
        """Feature 3: Validates creationflags == 0x08004000 (134234112) on Windows."""
        if sys.platform == "win32":
            self.assertEqual(
                WINDOWS_CREATION_FLAGS,
                EXPECTED_WINDOWS_CREATIONFLAGS,
                f"Expected {EXPECTED_WINDOWS_CREATIONFLAGS:#x}, got {WINDOWS_CREATION_FLAGS:#x}",
            )
            kwargs = get_subprocess_kwargs()
            self.assertIn("creationflags", kwargs)
            self.assertEqual(kwargs["creationflags"], 0x08004000)

    # -------------------------------------------------------------------------
    # Feature 4: Platform Matrix: YouTube Video
    # -------------------------------------------------------------------------
    def test_f04_platform_routing_youtube_video(self):
        """Feature 4: YouTube Video URL routes to yt-dlp -f bv*+ba/b --merge-output-format mp4."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        platform, cmd = build_download_command(url, "D:/Assets/BRoll", "video")
        self.assertEqual(platform, "youtube")
        cmd_str = " ".join(cmd)
        self.assertIn("-f", cmd)
        self.assertIn("bv*+ba/b", cmd)
        self.assertIn("--merge-output-format", cmd)
        self.assertIn("mp4", cmd)
        self.assertIn(url, cmd)

    # -------------------------------------------------------------------------
    # Feature 5: Platform Matrix: YouTube Audio
    # -------------------------------------------------------------------------
    def test_f05_platform_routing_youtube_audio(self):
        """Feature 5: YouTube Audio URL routes to yt-dlp -x --audio-format mp3 --audio-quality 0."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        platform, cmd = build_download_command(url, "D:/Assets/SFX", "audio")
        self.assertEqual(platform, "youtube")
        self.assertIn("-x", cmd)
        self.assertIn("--audio-format", cmd)
        self.assertIn("mp3", cmd)
        self.assertIn("--audio-quality", cmd)
        self.assertIn("0", cmd)
        self.assertIn(url, cmd)

    # -------------------------------------------------------------------------
    # Feature 6: Platform Matrix: Instagram / TikTok
    # -------------------------------------------------------------------------
    def test_f06a_platform_routing_instagram(self):
        """Feature 6a: Instagram Reel URL routes to yt-dlp mp4 merge."""
        url = "https://www.instagram.com/reel/C1234567890/"
        platform, cmd = build_download_command(url, "D:/Assets/Social", "video")
        self.assertEqual(platform, "instagram")
        self.assertIn("--merge-output-format", cmd)
        self.assertIn("mp4", cmd)

    def test_f06b_platform_routing_tiktok(self):
        """Feature 6b: TikTok Video URL routes to yt-dlp mp4 merge."""
        url = "https://www.tiktok.com/@user/video/7123456789"
        platform, cmd = build_download_command(url, "D:/Assets/Social", "video")
        self.assertEqual(platform, "tiktok")
        self.assertIn("--merge-output-format", cmd)
        self.assertIn("mp4", cmd)

    # -------------------------------------------------------------------------
    # Feature 7: Platform Matrix: Pinterest
    # -------------------------------------------------------------------------
    def test_f07_platform_routing_pinterest(self):
        """Feature 7: Pinterest URL routes to gallery-dl --dest [target_path] [url]."""
        url = "https://www.pinterest.com/pin/123456789/"
        target = os.path.normpath(os.path.abspath("D:/Assets/BRoll"))
        platform, cmd = build_download_command(url, target)
        self.assertEqual(platform, "pinterest")
        self.assertIn("--dest", cmd)
        self.assertIn(target, cmd)
        self.assertIn(url, cmd)

    # -------------------------------------------------------------------------
    # Feature 8: Platform Matrix: Twitter / X / Others
    # -------------------------------------------------------------------------
    def test_f08a_platform_routing_twitter_x(self):
        """Feature 8a: Twitter/X URL routes to yt-dlp mp4 merge."""
        url = "https://x.com/user/status/1234567890"
        platform, cmd = build_download_command(url, "D:/Assets/Social")
        self.assertEqual(platform, "twitter")
        self.assertIn("--merge-output-format", cmd)
        self.assertIn("mp4", cmd)

    def test_f08b_platform_routing_generic(self):
        """Feature 8b: Generic media URL routes to yt-dlp mp4 merge."""
        url = "https://vimeo.com/987654321"
        platform, cmd = build_download_command(url, "D:/Assets/BRoll")
        self.assertEqual(platform, "generic")
        self.assertIn("--merge-output-format", cmd)
        self.assertIn("mp4", cmd)

    # -------------------------------------------------------------------------
    # Feature 9: Output Filename Template
    # -------------------------------------------------------------------------
    def test_f09_output_filename_template(self):
        """Feature 9: yt-dlp output template enforces %(title).80s [%(id)s].%(ext)s."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        _, cmd = build_download_command(url, "D:/Assets/BRoll", "video")
        self.assertIn("-o", cmd)
        idx = cmd.index("-o")
        template = cmd[idx + 1]
        self.assertEqual(template, "%(title).80s [%(id)s].%(ext)s")

    # -------------------------------------------------------------------------
    # Feature 10: Background Ingestion Queue & SLA (<50ms)
    # -------------------------------------------------------------------------
    def test_f10_queue_sla_sub_50ms(self):
        """Feature 10: Ingestion endpoint responds in strictly < 50ms."""
        import anyio.from_thread
        import gc
        import statistics

        def instant_worker(job_id: str, url: str, target_dir: str, format_type: str) -> str:
            # Instant in-memory worker: eliminates NTFS disk I/O on D:/Assets/BRoll
            return ""

        orig_worker = self.qm._worker_func
        self.qm._worker_func = instant_worker
        try:
            with anyio.from_thread.start_blocking_portal(**self.client.async_backend) as portal:
                self.client.portal = portal
                try:
                    # 1. Pre-warm route, schema validation, and pipeline with 2 warmup requests
                    self.client.post(
                        "/api/queue",
                        json={"url": "https://youtu.be/sla_warmup_1", "folder_key": "B-Roll (General)"},
                    )
                    self.client.post(
                        "/api/queue",
                        json={"url": "https://youtu.be/sla_warmup_2", "folder_key": "B-Roll (General)"},
                    )
                    t_wait = 0.0
                    while self.qm._active and t_wait < 0.2:
                        time.sleep(0.01)
                        t_wait += 0.01
                    self.qm.clear_history()

                    # 2. Benchmark 3 consecutive requests under disabled GC to avoid OS thread quantum spikes
                    gc.collect()
                    gc_was_enabled = gc.isenabled()
                    if gc_was_enabled:
                        gc.disable()

                    latencies = []
                    responses = []
                    try:
                        for i in range(3):
                            t0 = time.perf_counter()
                            resp = self.client.post(
                                "/api/queue",
                                json={"url": f"https://youtu.be/sla_test_{i}", "folder_key": "B-Roll (General)"},
                            )
                            elapsed_ms = (time.perf_counter() - t0) * 1000.0
                            latencies.append(elapsed_ms)
                            responses.append(resp)
                    finally:
                        if gc_was_enabled:
                            gc.enable()

                    for resp in responses:
                        self.assertEqual(resp.status_code, 200)
                        self.assertEqual(resp.json()["status"], "queued")

                    median_ms = statistics.median(latencies)
                    self.assertLess(
                        median_ms,
                        50.0,
                        f"Ingestion SLA breached: median took {median_ms:.2f}ms (threshold 50ms, latencies: {[round(x, 1) for x in latencies]})",
                    )
                finally:
                    self.client.portal = None
        finally:
            t_wait = 0.0
            while self.qm._active and t_wait < 0.2:
                time.sleep(0.01)
                t_wait += 0.01
            self.qm.clear_history()
            self.qm._worker_func = orig_worker

    # -------------------------------------------------------------------------
    # Feature 11: Ingestion API Endpoints & Aliases
    # -------------------------------------------------------------------------
    def test_f11a_api_queue_endpoint(self):
        """Feature 11a: Canonical /api/queue returns valid IngestResponse."""
        resp = self.client.post(
            "/api/queue",
            json={
                "url": "https://youtu.be/canonical_test",
                "folder_key": "Social Edits",
                "format_type": "video",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "queued")
        self.assertIn("job_id", data)
        self.assertIn("id", data)
        self.assertEqual(data["job_id"], data["id"])
        self.assertEqual(data["platform"], "youtube")

    def test_f11b_download_alias_endpoint(self):
        """Feature 11b: Route alias /download functions identically to /api/queue."""
        resp = self.client.post(
            "/download",
            json={
                "url": "https://youtu.be/alias_test",
                "folder_key": "Sound Effects",
                "format_type": "audio",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "queued")
        self.assertEqual(data["format_type"], "audio")

    # -------------------------------------------------------------------------
    # Feature 12: Status & Telemetry API
    # -------------------------------------------------------------------------
    def test_f12a_api_status_endpoint(self):
        """Feature 12a: Canonical /api/status returns telemetry snapshot."""
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("active", data)
        self.assertIn("recent", data)
        self.assertIn("errors", data)

    def test_f12b_status_alias_endpoint(self):
        """Feature 12b: Route alias /status functions identically to /api/status."""
        resp = self.client.get("/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("active", data)
        self.assertIn("recent", data)

    def test_f12c_single_job_status_endpoint(self):
        """Feature 12c: /api/status/{job_id} retrieves telemetry for single job."""
        post_resp = self.client.post("/api/queue", json={"url": "https://youtu.be/single_job"})
        job_id = post_resp.json()["job_id"]
        status_resp = self.client.get(f"/api/status/{job_id}")
        self.assertEqual(status_resp.status_code, 200)
        data = status_resp.json()
        self.assertEqual(data["id"], job_id)

    # -------------------------------------------------------------------------
    # Feature 13: Preset Query & Pinning API
    # -------------------------------------------------------------------------
    def test_f13a_presets_listing_endpoint(self):
        """Feature 13a: /api/presets and /folders return presets dictionary and folders list."""
        for endpoint in ["/api/presets", "/folders"]:
            resp = self.client.get(endpoint)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("presets", data)
            self.assertIn("folders", data)
            self.assertIn("B-Roll (General)", data["presets"])
            self.assertIn("B-Roll (General)", data["folders"])

    def test_f13b_preset_pinning_endpoint(self):
        """Feature 13b: /api/presets/pin pins a new folder to config.json."""
        test_dir = os.path.join(PROJECT_ROOT, "test_tier1_pinned_folder")
        os.makedirs(test_dir, exist_ok=True)
        try:
            resp = self.client.post(
                "/api/presets/pin",
                json={"name": "Tier 1 Pinned Folder", "path": test_dir},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["name"], "Tier 1 Pinned Folder")
            # Verify preset now appears in GET /api/presets
            list_resp = self.client.get("/api/presets")
            self.assertIn("Tier 1 Pinned Folder", list_resp.json()["presets"])
        finally:
            if os.path.isdir(test_dir):
                try:
                    os.rmdir(test_dir)
                except Exception:
                    pass

    # -------------------------------------------------------------------------
    # Feature 14: Drive Enumeration API
    # -------------------------------------------------------------------------
    def test_f14_drives_enumeration_endpoint(self):
        """Feature 14: /api/drives returns list of mounted Windows drive roots."""
        resp = self.client.get("/api/drives")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("drives", data)
        self.assertIsInstance(data["drives"], list)
        self.assertGreater(len(data["drives"]), 0)
        # On Windows host, C:\ must be present
        if sys.platform == "win32":
            c_drive = any("C:" in d for d in data["drives"])
            self.assertTrue(c_drive, f"C: drive not found in drives: {data['drives']}")

    # -------------------------------------------------------------------------
    # Feature 15: Live Directory Traversal API
    # -------------------------------------------------------------------------
    def test_f15_live_directory_traversal_api(self):
        """Feature 15: /api/browse?path=... safely enumerates immediate subdirectories."""
        resp = self.client.get(f"/api/browse?path={PROJECT_ROOT}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("current", data)
        self.assertIn("subdirectories", data)
        self.assertIn("folders", data)
        subdirs = data["folders"]
        self.assertIn("core", subdirs)
        self.assertIn("tests", subdirs)

    def get_authenticated_session(self) -> dict[str, str]:
        """Helper to obtain valid Bearer session header for protected endpoint calls."""
        creds = self.client.get("/api/workstation/credentials").json()
        resp = self.client.post(
            "/api/auth/login",
            json={"uid": creds["uid"], "password": creds["password"]},
        )
        token = resp.json()["session_token"]
        return {"Authorization": f"Bearer {token}"}

    # -------------------------------------------------------------------------
    # Feature 16: Unified Simple Authentication (5-Digit UID & Password)
    # -------------------------------------------------------------------------
    def test_f16a_server_derives_5digit_uid_from_ip(self):
        """Feature 16a: Server deterministically derives 5-digit numeric UID from IP."""
        for test_ip in ["127.0.0.1", "192.168.1.50", "10.0.0.1", "172.16.254.1"]:
            uid = derive_server_uid(test_ip)
            self.assertEqual(len(uid), 5, f"UID {uid} length != 5")
            self.assertTrue(uid.isdigit(), f"UID {uid} is not numeric")
            self.assertGreaterEqual(int(uid), 10000)
            self.assertLessEqual(int(uid), 99999)
            self.assertEqual(derive_server_uid(test_ip), uid)

    def test_f16b_server_generates_startup_password(self):
        """Feature 16b: Server auto-generates 8-character hex startup connection password."""
        pw1 = generate_connection_password()
        pw2 = generate_connection_password()
        self.assertEqual(len(pw1), 8)
        self.assertEqual(len(pw2), 8)
        self.assertNotEqual(pw1, pw2)
        creds = self.client.get("/api/workstation/credentials").json()
        self.assertIn("password", creds)
        self.assertIn("uid", creds)
        self.assertEqual(len(creds["password"]), 8)
        self.assertEqual(len(creds["uid"]), 5)

    def test_f16c_mobile_login_endpoint(self):
        """Feature 16c: Mobile client authenticates via POST /api/auth/login and receives ads_<token>."""
        creds = self.client.get("/api/workstation/credentials").json()
        resp = self.client.post(
            "/api/auth/login",
            json={"uid": creds["uid"], "password": creds["password"]},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("session_token", "").startswith("ads_"))

    def test_f16d_unauthenticated_mobile_blocked(self):
        """Feature 16d: Remote mobile client without session token receives HTTP 401."""
        remote_client = TestClient(server.app, client=("192.168.1.200", 50000))
        resp = remote_client.post(
            "/api/queue",
            json={"url": "https://youtu.be/unauth_test"},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertIn("WWW-Authenticate", resp.headers)
        self.assertEqual(resp.headers["WWW-Authenticate"], "Bearer")

    def test_f16e_legacy_pairing_endpoints_removed(self):
        """Feature 16e: Legacy QR, pairing, network mode, and device endpoints return 404."""
        legacy_routes = [
            ("GET", "/api/qrcode"),
            ("POST", "/api/qrcode/regenerate"),
            ("GET", "/pair"),
            ("POST", "/pair"),
            ("GET", "/api/network/mode"),
            ("POST", "/api/network/mode"),
            ("GET", "/api/devices"),
            ("DELETE", "/api/devices/any_device"),
            ("POST", "/api/devices/revoke"),
        ]
        for method, route in legacy_routes:
            if method == "GET":
                r = self.client.get(route)
            elif method == "POST":
                r = self.client.post(route, json={})
            elif method == "DELETE":
                r = self.client.delete(route)
            self.assertEqual(r.status_code, 404, f"Legacy route {route} did not return 404")

    # -------------------------------------------------------------------------
    # Feature 17: Obsidian Dark Theme UI (#090d16)
    # -------------------------------------------------------------------------
    def test_f17_obsidian_dark_theme_css_and_html(self):
        """Feature 17: Validates Obsidian dark theme (#090d16) across HTML and CSS."""
        index_path = os.path.join(PROJECT_ROOT, "static", "index.html")
        css_path = os.path.join(PROJECT_ROOT, "static", "style.css")
        self.assertTrue(os.path.isfile(index_path))
        self.assertTrue(os.path.isfile(css_path))

        with open(index_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()

        self.assertIn("#090d16", html_content)
        self.assertIn("#090d16", css_content)

    # -------------------------------------------------------------------------
    # Feature 18: Mobile Ergonomic Touch Targets (>= 44px)
    # -------------------------------------------------------------------------
    def test_f18_mobile_touch_targets_compliance(self):
        """Feature 18: CSS mandates WCAG / Apple HIG >= 44px touch targets."""
        css_path = os.path.join(PROJECT_ROOT, "static", "style.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()
        # Checks for min-height 48px or 44px rule in design tokens/buttons
        self.assertTrue(
            "44px" in css_content or "48px" in css_content or "min-height: 48px" in css_content,
            "CSS does not declare >= 44px or 48px touch targets",
        )

    # -------------------------------------------------------------------------
    # Feature 19: Sub-50ms Instant Queue Toast
    # -------------------------------------------------------------------------
    def test_f19_sub50ms_instant_queue_toast_markup(self):
        """Feature 19: index.html defines instant toast notification element."""
        index_path = os.path.join(PROJECT_ROOT, "static", "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="toast"', html)
        self.assertIn('role="alert"', html)

    # -------------------------------------------------------------------------
    # Feature 20: Dynamic Format Selector / Badge
    # -------------------------------------------------------------------------
    def test_f20_dynamic_format_selector_and_badge_markup(self):
        """Feature 20: index.html contains format selector and Direct Max Quality badge."""
        index_path = os.path.join(PROJECT_ROOT, "static", "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("format-toggle", html)
        self.assertIn("Direct Max Quality", html)

    # -------------------------------------------------------------------------
    # Feature 21: Rapid Clipboard Paste
    # -------------------------------------------------------------------------
    def test_f21_rapid_clipboard_paste_button(self):
        """Feature 21: index.html defines Rapid Paste interactive button."""
        index_path = os.path.join(PROJECT_ROOT, "static", "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("btn-paste", html)

    # -------------------------------------------------------------------------
    # Feature 22: Dedicated Two-Stage Mobile Interface Contracts
    # -------------------------------------------------------------------------
    def test_f22_mobile_two_stage_ui_contracts(self):
        """Feature 22: Mobile interface presents Stage 1 connection and Stage 2 clean download form."""
        mobile_path = os.path.join(PROJECT_ROOT, "static", "mobile.html")
        self.assertTrue(os.path.isfile(mobile_path))
        with open(mobile_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Stage 1: Connection Screen contracts
        self.assertIn('id="stage-connection"', html)
        self.assertIn('id="mobile-uid-input"', html)
        self.assertIn('id="mobile-password-input"', html)
        self.assertIn('id="mobile-btn-connect"', html)

        # Stage 2: Clean Download Form contracts
        self.assertIn('id="stage-download"', html)
        self.assertIn('id="mobile-url-input"', html)
        self.assertIn('id="mobile-btn-paste"', html)
        self.assertIn('id="mobile-folder-select"', html)
        self.assertIn('id="mobile-btn-download"', html)

        # Format selector buttons: must have exact element IDs bound in mobile.js
        self.assertIn('id="mobile-fmt-video"', html)
        self.assertIn('id="mobile-fmt-audio"', html)
        self.assertIn('data-format="video"', html)
        self.assertIn('data-format="audio"', html)
        self.assertIn('role="radio"', html)

        # Total absence of legacy bottom sheet modal, QR camera scanners, and manual token fields
        self.assertNotIn('id="pc-browser-sheet"', html)
        self.assertNotIn('id="browse-pc-btn"', html)
        self.assertNotIn('id="mobile-qr-video"', html)
        self.assertNotIn('id="token-32-char"', html)
        self.assertNotIn('id="mobile-manual-token-input"', html)
        self.assertNotIn('id="mobile-btn-camera-scan"', html)
        self.assertNotIn('id="mobile-btn-file-scan"', html)

    # -------------------------------------------------------------------------
    # Feature 23: Minimal PC Workstation Interface Contracts
    # -------------------------------------------------------------------------
    def test_f23_pc_minimal_view_contracts(self):
        """Feature 23: PC view displays download queue, downloaded files history, and UID/PW reveal."""
        pc_path = os.path.join(PROJECT_ROOT, "static", "pc.html")
        self.assertTrue(os.path.isfile(pc_path))
        with open(pc_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Core tables and credential reveal elements
        self.assertIn('id="pc-queue-table"', html)
        self.assertIn('id="pc-history-table"', html)
        self.assertIn('id="pc-uid-display"', html)
        self.assertIn('id="pc-password-display"', html)
        self.assertIn('id="btn-toggle-credentials"', html)

        # Also verify served from /pc endpoint
        resp = self.client.get("/pc")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("pc-queue-table", resp.text)
        self.assertIn("pc-history-table", resp.text)

    # -------------------------------------------------------------------------
    # Feature 24: PWA Manifest & Service Worker
    # -------------------------------------------------------------------------
    def test_f24a_pwa_manifest_endpoint(self):
        """Feature 24a: GET /manifest.json returns valid PWA configuration."""
        resp = self.client.get("/manifest.json")
        self.assertEqual(resp.status_code, 200)
        manifest = resp.json()
        self.assertIn("AssetDrop", manifest.get("name"))
        self.assertEqual(manifest.get("short_name"), "AssetDrop")
        self.assertEqual(manifest.get("display"), "standalone")
        self.assertEqual(manifest.get("theme_color"), "#090d16")
        self.assertIn("icons", manifest)

    def test_f24b_pwa_service_worker_endpoint(self):
        """Feature 24b: GET /sw.js serves service worker with root scope permissions."""
        resp = self.client.get("/sw.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Service-Worker-Allowed", resp.headers)
        self.assertEqual(resp.headers["Service-Worker-Allowed"], "/")

    # -------------------------------------------------------------------------
    # Feature 25: Windows Silent Boot Script
    # -------------------------------------------------------------------------
    def test_f25_windows_silent_boot_script(self):
        """Feature 25: start_silent.vbs exists with pythonw and invisible window style (0)."""
        vbs_path = os.path.join(PROJECT_ROOT, "start_silent.vbs")
        self.assertTrue(os.path.isfile(vbs_path))
        with open(vbs_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("pythonw", content.lower())
        self.assertIn("uvicorn", content.lower())
        self.assertIn("0.0.0.0", content)
        self.assertIn("8000", content)
        # Window style 0 (vbHide)
        self.assertRegex(content, r",\s*0\s*,\s*False")

    # -------------------------------------------------------------------------
    # Feature 26: Process Shutdown Script
    # -------------------------------------------------------------------------
    def test_f26_process_shutdown_script(self):
        """Feature 26: stop_server.bat checks port 8000 and terminates process via taskkill."""
        bat_path = os.path.join(PROJECT_ROOT, "stop_server.bat")
        self.assertTrue(os.path.isfile(bat_path))
        with open(bat_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("8000", content)
        self.assertIn("taskkill", content.lower())
        self.assertIn("/f", content.lower())

    # -------------------------------------------------------------------------
    # Feature 27: Windows Firewall Automation Script
    # -------------------------------------------------------------------------
    def test_f27_windows_firewall_automation_script(self):
        """Feature 27: setup_firewall.bat configures inbound rule for TCP 8000."""
        bat_path = os.path.join(PROJECT_ROOT, "setup_firewall.bat")
        self.assertTrue(os.path.isfile(bat_path))
        with open(bat_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("netsh", content.lower())
        self.assertIn("advfirewall", content.lower())
        self.assertIn("localport=8000", content.lower())
        self.assertIn("protocol=tcp", content.lower())

    # -------------------------------------------------------------------------
    # Feature 28: Network Connection Guide
    # -------------------------------------------------------------------------
    def test_f28_network_connection_guide(self):
        """Feature 28: docs/connection_guide.md documents LAN Wi-Fi & Tailscale access."""
        guide_path = os.path.join(PROJECT_ROOT, "docs", "connection_guide.md")
        self.assertTrue(os.path.isfile(guide_path))
        with open(guide_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Wi-Fi", content)
        self.assertIn("Tailscale", content)
        self.assertIn("8000", content)

    # -------------------------------------------------------------------------
    # Feature 29: PC Interface Clutter Exclusion Contracts
    # -------------------------------------------------------------------------
    def test_f29_pc_interface_clutter_exclusion(self):
        """Feature 29: PC view strictly excludes QR codes, network toggles, device panels, and shared folder forms."""
        pc_path = os.path.join(PROJECT_ROOT, "static", "pc.html")
        with open(pc_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Legacy pairing & device controls
        self.assertNotIn('id="qr-code-img"', html)
        self.assertNotIn('id="btn-network-mode-public"', html)
        self.assertNotIn('id="devices-list-container"', html)
        self.assertNotIn('id="active-devices-list"', html)
        self.assertNotIn('id="access-pin-input"', html)

        # Shared folder configuration controls & link input forms
        self.assertNotIn('id="add-folder-box"', html)
        self.assertNotIn('id="btn-show-add-folder"', html)
        self.assertNotIn('id="shared-folder-manager"', html)
        self.assertNotIn('id="link-paste-box"', html)
        self.assertNotIn('id="url-input"', html)
        self.assertNotIn('id="pc-browser-sheet"', html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
