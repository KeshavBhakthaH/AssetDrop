"""
tests/test_challenger_m3p_2_android_api.py — Empirical Adversarial Challenge Suite 2 for Milestone M3-P.

Challenger 2 Empirical Verification:
1. Android Capacitor Sync & Packaging Resilience:
   - node mobile/build.js execution, idempotence, and clean directory recovery.
   - Exact bit-for-bit SHA256 parity between static/ and mobile/www/ assets.
   - mobile/capacitor.config.json schema, webDir, cleartext, and dark background verification.
2. Two-Stage Mobile DOM & Negative Clutter Sweep:
   - mobile/www/index.html structural integrity (#stage-connection, #stage-download, #toast).
   - Strict absence of all legacy peripheral clutter (video, canvas, QR scanners, 32-char token, sheets, trays).
   - WCAG 2.5.5 touch target size (min-height >= 44px) verification in mobile.css.
3. End-to-End API Workflows & Security Limits:
   - Unauthenticated remote calls return HTTP 401.
   - Tampered / forged / fabricated session tokens return HTTP 401.
   - Login fuzzing (empty, missing, non-numeric, wrong password, injection) -> 422/401, 0 crashes.
   - Correct UID & Password login -> HTTP 200, valid ads_ token.
   - Authenticated remote calls with Bearer token successfully access /api/shared-folders and /api/queue (<50ms SLA).
   - Folder resolution via preset name and phone-safe SHA256 slice ID.
   - Format normalization (MP3 -> audio, MP4 -> video).
   - Token revocation on /api/auth/logout and immediate subsequent 401 rejection.
   - Workstation-only endpoints (credentials, drives, browse, pin) strictly return 403 Forbidden for remote clients.
   - Arbitrary path traversal blocked with 400 Bad Request for remote clients.
   - Burst rate limiting: 10/min allowed, 11th request returns HTTP 429.
   - Route dispatching and method not allowed (405) enforcement.
"""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unittest
from typing import Any, Dict, List, Optional, Set, Tuple

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from starlette.testclient import TestClient

import server
from core.auth import clear_all_sessions, verify_session_token, get_active_session_count
from core.config import get_presets, load_config
from core.queue_manager import get_queue_manager
from core.security_limits import reset_download_rate_limit
from tests.mock_cli import simulated_worker_func

STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
MOBILE_DIR = os.path.join(PROJECT_ROOT, "mobile")
MOBILE_WWW_DIR = os.path.join(MOBILE_DIR, "www")
BUILD_JS_PATH = os.path.join(MOBILE_DIR, "build.js")
CAPACITOR_CONFIG_PATH = os.path.join(MOBILE_DIR, "capacitor.config.json")


def sha256_file(filepath: str) -> str:
    """Computes SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def read_text(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


class ChallengeDOMInspector(HTMLParser):
    """HTML5 DOM inspector to capture elements, IDs, classes, and tags."""

    def __init__(self):
        super().__init__()
        self.tags: List[str] = []
        self.ids: Dict[str, Tuple[str, Dict[str, str]]] = {}
        self.classes: Set[str] = set()
        self.elements: List[Dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attr_dict = {k: v or "" for k, v in attrs}
        self.tags.append(tag)
        el_id = attr_dict.get("id")
        if el_id:
            self.ids[el_id] = (tag, attr_dict)
        cls_str = attr_dict.get("class", "")
        for c in cls_str.split():
            self.classes.add(c)
        self.elements.append({"tag": tag, "attrs": attr_dict, "id": el_id, "class": cls_str})


class TestChallengerM3P2AndroidAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.init_server_credentials(force_refresh=True)
        cls.client = TestClient(server.app)
        cls.qm = get_queue_manager()
        cls.qm._worker_func = simulated_worker_func

    def setUp(self):
        # Reset server credentials and session store
        creds = server.init_server_credentials(force_refresh=False)
        self.server_uid = creds["uid"]
        self.server_password = creds["password"]
        self.remote_ip = "192.168.1.188"
        self.remote_headers = {"X-Forwarded-For": self.remote_ip}
        reset_download_rate_limit(self.remote_ip)

    # =========================================================================
    # SECTION 1: Android Capacitor Build Sync & Asset Packaging Resilience
    # =========================================================================

    def test_01_capacitor_build_script_idempotency_and_clean_run(self):
        """Assert node mobile/build.js executes cleanly with code 0 and is idempotent."""
        # Run 1
        res1 = subprocess.run(
            ["node", BUILD_JS_PATH],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res1.returncode, 0, f"mobile/build.js failed on run 1: {res1.stderr}")
        self.assertIn("Synced static/mobile.html -> mobile/www/index.html", res1.stdout)

        # Run 2 (Idempotency)
        res2 = subprocess.run(
            ["node", BUILD_JS_PATH],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res2.returncode, 0, f"mobile/build.js failed on idempotent run 2: {res2.stderr}")

    def test_02_capacitor_asset_hash_and_content_parity(self):
        """Assert exact bit-for-bit SHA-256 parity between static/ and mobile/www/ assets."""
        file_pairs = [
            (os.path.join(STATIC_DIR, "mobile.html"), os.path.join(MOBILE_WWW_DIR, "index.html")),
            (os.path.join(STATIC_DIR, "mobile.js"), os.path.join(MOBILE_WWW_DIR, "mobile.js")),
            (os.path.join(STATIC_DIR, "mobile.css"), os.path.join(MOBILE_WWW_DIR, "mobile.css")),
            (os.path.join(STATIC_DIR, "mobile.js"), os.path.join(MOBILE_WWW_DIR, "static", "mobile.js")),
            (os.path.join(STATIC_DIR, "mobile.css"), os.path.join(MOBILE_WWW_DIR, "static", "mobile.css")),
            (os.path.join(STATIC_DIR, "manifest.json"), os.path.join(MOBILE_WWW_DIR, "manifest.json")),
            (os.path.join(STATIC_DIR, "sw.js"), os.path.join(MOBILE_WWW_DIR, "sw.js")),
        ]

        for src, dest in file_pairs:
            self.assertTrue(os.path.isfile(src), f"Source file does not exist: {src}")
            self.assertTrue(os.path.isfile(dest), f"Synced destination file does not exist: {dest}")
            src_hash = sha256_file(src)
            dest_hash = sha256_file(dest)
            self.assertEqual(
                src_hash,
                dest_hash,
                f"SHA-256 mismatch between {os.path.basename(src)} ({src_hash}) and {os.path.basename(dest)} ({dest_hash})",
            )

    def test_03_capacitor_resilience_recovery_after_wipe(self):
        """Assert build.js successfully recovers when mobile/www/index.html is deleted."""
        target_index = os.path.join(MOBILE_WWW_DIR, "index.html")
        if os.path.exists(target_index):
            os.remove(target_index)
        self.assertFalse(os.path.exists(target_index), "Target file was not removed for recovery test")

        res = subprocess.run(
            ["node", BUILD_JS_PATH],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Recovery build failed: {res.stderr}")
        self.assertTrue(os.path.isfile(target_index), "Recovery build failed to restore mobile/www/index.html")
        src_html = os.path.join(STATIC_DIR, "mobile.html")
        self.assertEqual(sha256_file(src_html), sha256_file(target_index))

    def test_04_capacitor_config_json_contracts(self):
        """Assert mobile/capacitor.config.json matches all native Android runtime requirements."""
        self.assertTrue(os.path.isfile(CAPACITOR_CONFIG_PATH), "capacitor.config.json not found")
        with open(CAPACITOR_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        self.assertEqual(cfg.get("webDir"), "www", "webDir must point to 'www'")
        self.assertEqual(cfg.get("appName"), "AssetDrop")
        self.assertTrue(cfg.get("appId", "").startswith("com.assetdrop"), "Invalid appId format")

        server_cfg = cfg.get("server", {})
        self.assertTrue(server_cfg.get("cleartext"), "Capacitor server.cleartext must be True for LAN Wi-Fi HTTP")
        self.assertEqual(server_cfg.get("androidScheme"), "http")

        android_cfg = cfg.get("android", {})
        self.assertEqual(android_cfg.get("backgroundColor"), "#09090b", "Native window background must be dark #09090b")

    # =========================================================================
    # SECTION 2: Two-Stage Mobile DOM & Negative Clutter Sweep
    # =========================================================================

    def test_05_mobile_www_index_two_stage_dom_structure(self):
        """Assert mobile/www/index.html contains exact two-stage architecture elements."""
        content = read_text(os.path.join(MOBILE_WWW_DIR, "index.html"))
        dom = ChallengeDOMInspector()
        dom.feed(content)

        # Stage 1 Connection Screen
        self.assertIn("stage-connection", dom.ids)
        _, stage1_attrs = dom.ids["stage-connection"]
        self.assertNotIn("hidden", stage1_attrs.get("class", ""))

        self.assertIn("mobile-auth-form", dom.ids)
        self.assertIn("mobile-uid-input", dom.ids)
        self.assertIn("mobile-password-input", dom.ids)
        self.assertIn("mobile-btn-connect", dom.ids)
        self.assertIn("mobile-auth-error", dom.ids)

        # UID input attributes
        _, uid_attrs = dom.ids["mobile-uid-input"]
        self.assertEqual(uid_attrs.get("inputmode"), "numeric")
        self.assertEqual(uid_attrs.get("maxlength"), "5")
        self.assertEqual(uid_attrs.get("pattern"), "[0-9]{5}")

        # Stage 2 Download Screen
        self.assertIn("stage-download", dom.ids)
        _, stage2_attrs = dom.ids["stage-download"]
        self.assertIn("hidden", stage2_attrs.get("class", ""))

        self.assertIn("mobile-connected-text", dom.ids)
        self.assertIn("mobile-btn-disconnect", dom.ids)
        self.assertIn("mobile-download-form", dom.ids)
        self.assertIn("mobile-url-input", dom.ids)
        self.assertIn("mobile-btn-paste", dom.ids)
        self.assertIn("mobile-fmt-video", dom.ids)
        self.assertIn("mobile-fmt-audio", dom.ids)
        self.assertIn("mobile-folder-select", dom.ids)
        self.assertIn("mobile-btn-download", dom.ids)

        # Toast notification system
        self.assertIn("toast", dom.ids)
        self.assertIn("toast-icon", dom.ids)
        self.assertIn("toast-message", dom.ids)

    def test_06_mobile_www_index_strict_negative_clutter_sweep(self):
        """Assert complete absence of peripheral clutter from mobile/www/index.html."""
        content = read_text(os.path.join(MOBILE_WWW_DIR, "index.html"))
        dom = ChallengeDOMInspector()
        dom.feed(content)

        # No video or canvas elements
        self.assertEqual(len([el for el in dom.elements if el["tag"] == "video"]), 0)
        self.assertEqual(len([el for el in dom.elements if el["tag"] == "canvas"]), 0)

        # Prohibited legacy IDs
        prohibited_ids = [
            "mobile-scanner-wrapper",
            "mobile-qr-video",
            "btn-close-scanner",
            "mobile-btn-camera-scan",
            "mobile-btn-file-scan",
            "mobile-manual-token-input",
            "btn-submit-manual-token",
            "qr-code-img",
            "btn-regenerate-qr",
            "btn-network-mode-public",
            "btn-network-mode-trusted",
            "devices-card",
            "pc-browser-sheet",
            "sheet-backdrop",
            "status-tray",
            "preset-chips-container",
        ]
        for pid in prohibited_ids:
            self.assertNotIn(pid, dom.ids, f"Prohibited legacy element #{pid} found in mobile/www/index.html")

        # Prohibited regex strings
        prohibited_phrases = [
            r"Scan QR",
            r"Camera",
            r"Upload QR",
            r"Paste 32-char token",
            r"Public Network",
            r"Trusted Studio",
            r"Browse PC\.\.\.",
            r"pc-browser-sheet",
            r"status-tray",
        ]
        for pat in prohibited_phrases:
            matches = re.findall(pat, content, re.IGNORECASE)
            self.assertEqual(len(matches), 0, f"Prohibited phrase '{pat}' found in mobile/www/index.html")

    def test_07_wcag_touch_targets_in_mobile_css(self):
        """Assert CSS rules mandate min-height >= 44px on all interactive elements for touch ergonomics."""
        css_content = read_text(os.path.join(MOBILE_WWW_DIR, "mobile.css"))

        interactive_selectors = [
            r"\.btn\s*\{[^}]*\}",
            r"\.field-input\s*\{[^}]*\}",
            r"\.field-select\s*\{[^}]*\}",
            r"\.segment-btn\s*\{[^}]*\}",
            r"\.btn-disconnect\s*\{[^}]*\}",
            r"\.btn-download\s*\{[^}]*\}",
        ]

        for pattern in interactive_selectors:
            match = re.search(pattern, css_content)
            self.assertIsNotNone(match, f"Missing CSS selector matching {pattern}")
            block = match.group(0)
            h_match = re.search(r"min-height\s*:\s*(\d+)px", block)
            self.assertIsNotNone(h_match, f"Rule block missing min-height:\n{block}")
            min_h = int(h_match.group(1))
            self.assertGreaterEqual(min_h, 44, f"min-height {min_h}px violates WCAG 2.5.5 in:\n{block}")

    # =========================================================================
    # SECTION 3: End-to-End API Workflows & Security Limits
    # =========================================================================

    def test_08_remote_unauthenticated_requests_return_401(self):
        """Assert unauthenticated remote requests to protected endpoints return HTTP 401."""
        endpoints = [
            ("POST", "/api/queue", {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "folder_key": "B-Roll (General)"}),
            ("POST", "/download", {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "folder_key": "B-Roll (General)"}),
            ("GET", "/api/shared-folders", None),
            ("GET", "/folders", None),
        ]

        for method, endpoint, payload in endpoints:
            if method == "POST":
                res = self.client.post(endpoint, headers=self.remote_headers, json=payload)
            else:
                res = self.client.get(endpoint, headers=self.remote_headers)

            self.assertEqual(
                res.status_code,
                401,
                f"Unauthenticated {method} {endpoint} returned {res.status_code} instead of 401",
            )

    def test_09_remote_tampered_and_forged_tokens_return_401(self):
        """Assert tampered, truncated, or fabricated session tokens return HTTP 401."""
        bogus_tokens = [
            "",
            "Bearer",
            "Bearer ",
            "Bearer ads_",
            "Bearer ads_fake123",
            "Bearer ads_00000000000000000000000000000000",
            "Bearer 12345",
            "Bearer invalid_random_token_string",
        ]

        for bogus in bogus_tokens:
            h = dict(self.remote_headers)
            if bogus:
                h["Authorization"] = bogus
            res = self.client.get("/api/shared-folders", headers=h)
            self.assertEqual(res.status_code, 401, f"Bogus token '{bogus}' returned {res.status_code} instead of 401")

            res_q = self.client.post(
                "/api/queue",
                headers=h,
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            self.assertEqual(res_q.status_code, 401, f"Bogus token '{bogus}' on /api/queue returned {res_q.status_code}")

    def test_10_auth_login_fuzzing_and_boundary_rejection(self):
        """Assert login endpoint rejects invalid bodies, wrong UIDs, and wrong passwords with 422 or 401."""
        # 1. Missing fields (422)
        res_empty = self.client.post("/api/auth/login", headers=self.remote_headers, json={})
        self.assertEqual(res_empty.status_code, 422)

        res_no_pw = self.client.post("/api/auth/login", headers=self.remote_headers, json={"uid": self.server_uid})
        self.assertEqual(res_no_pw.status_code, 422)

        res_no_uid = self.client.post("/api/auth/login", headers=self.remote_headers, json={"password": self.server_password})
        self.assertEqual(res_no_uid.status_code, 422)

        # 2. Wrong UID, correct password (401)
        res_wrong_uid = self.client.post(
            "/api/auth/login",
            headers=self.remote_headers,
            json={"uid": "00000", "password": self.server_password},
        )
        self.assertEqual(res_wrong_uid.status_code, 401)

        # 3. Correct UID, wrong password (401)
        res_wrong_pw = self.client.post(
            "/api/auth/login",
            headers=self.remote_headers,
            json={"uid": self.server_uid, "password": "wrong_password_xyz"},
        )
        self.assertEqual(res_wrong_pw.status_code, 401)

        # 4. Alphanumeric / non-digit UID (401)
        res_alpha = self.client.post(
            "/api/auth/login",
            headers=self.remote_headers,
            json={"uid": "ABCDE", "password": self.server_password},
        )
        self.assertEqual(res_alpha.status_code, 401)

        # 5. Injection payloads (401, zero crashes)
        injection_payloads = [
            {"uid": "' OR '1'='1", "password": "' OR '1'='1"},
            {"uid": "<script>alert(1)</script>", "password": "pass"},
            {"uid": self.server_uid, "password": "A" * 10000},
            {"uid": "99999\x00", "password": "pass\x00"},
        ]
        for inj in injection_payloads:
            res_inj = self.client.post("/api/auth/login", headers=self.remote_headers, json=inj)
            self.assertEqual(res_inj.status_code, 401, f"Injection payload caused {res_inj.status_code}")

    def test_11_auth_login_success_and_token_format(self):
        """Assert correct UID & password login returns HTTP 200 with valid ads_ session token."""
        res = self.client.post(
            "/api/auth/login",
            headers=self.remote_headers,
            json={"uid": self.server_uid, "password": self.server_password},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        token = data.get("session_token")
        self.assertIsNotNone(token)
        self.assertTrue(token.startswith("ads_"))
        self.assertEqual(len(token), 36)  # ads_ (4 chars) + 32 hex chars
        self.assertTrue(verify_session_token(token), "Created token failed in-memory verification")

    def test_12_authenticated_mobile_workflow_folders_and_enqueue(self):
        """Assert authenticated mobile client can query folders and enqueue tasks within 50ms SLA."""
        # 1. Login
        res_login = self.client.post(
            "/api/auth/login",
            headers=self.remote_headers,
            json={"uid": self.server_uid, "password": self.server_password},
        )
        token = res_login.json()["session_token"]
        auth_headers = dict(self.remote_headers)
        auth_headers["Authorization"] = f"Bearer {token}"

        # 2. Query shared folders
        res_folders = self.client.get("/api/shared-folders", headers=auth_headers)
        self.assertEqual(res_folders.status_code, 200)
        f_data = res_folders.json()
        self.assertIn("folders", f_data)
        folders = f_data["folders"]
        self.assertGreater(len(folders), 0)
        first_folder_name = folders[0]["name"]

        # 3. Enqueue download with preset name within 50ms SLA
        reset_download_rate_limit(self.remote_ip)
        t0 = time.perf_counter()
        res_queue = self.client.post(
            "/api/queue",
            headers=auth_headers,
            json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "format_type": "video",
                "folder_key": first_folder_name,
            },
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res_queue.status_code, 200, f"Queue failed: {res_queue.text}")
        q_data = res_queue.json()
        self.assertEqual(q_data["status"], "queued")
        self.assertTrue(bool(q_data.get("job_id")))
        self.assertLess(elapsed_ms, 50.0, f"Latency {elapsed_ms:.2f}ms exceeded 50ms SLA")

    def test_13_authenticated_queue_with_folder_id_hash(self):
        """Assert remote queue submission succeeds when referencing phone-safe folder ID slice."""
        res_login = self.client.post(
            "/api/auth/login",
            headers=self.remote_headers,
            json={"uid": self.server_uid, "password": self.server_password},
        )
        token = res_login.json()["session_token"]
        auth_headers = dict(self.remote_headers)
        auth_headers["Authorization"] = f"Bearer {token}"

        res_folders = self.client.get("/api/shared-folders", headers=auth_headers)
        folder_id = res_folders.json()["folders"][0]["id"]
        self.assertEqual(len(folder_id), 8)

        reset_download_rate_limit(self.remote_ip)
        res_queue = self.client.post(
            "/api/queue",
            headers=auth_headers,
            json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "format_type": "video",
                "folder_key": folder_id,
            },
        )
        self.assertEqual(res_queue.status_code, 200)
        self.assertEqual(res_queue.json()["status"], "queued")

    def test_14_authenticated_queue_format_normalization(self):
        """Assert format_type normalization handles mp3/audio and mp4/video appropriately."""
        res_login = self.client.post(
            "/api/auth/login",
            headers=self.remote_headers,
            json={"uid": self.server_uid, "password": self.server_password},
        )
        token = res_login.json()["session_token"]
        auth_headers = dict(self.remote_headers)
        auth_headers["Authorization"] = f"Bearer {token}"

        # audio / mp3
        reset_download_rate_limit(self.remote_ip)
        res_audio = self.client.post(
            "/api/queue",
            headers=auth_headers,
            json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "format_type": "mp3",
                "folder_key": "B-Roll (General)",
            },
        )
        self.assertEqual(res_audio.status_code, 200)
        self.assertEqual(res_audio.json()["format_type"], "audio")

        # video / mp4
        reset_download_rate_limit(self.remote_ip)
        res_video = self.client.post(
            "/api/queue",
            headers=auth_headers,
            json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "format_type": "video",
                "folder_key": "B-Roll (General)",
            },
        )
        self.assertEqual(res_video.status_code, 200)
        self.assertEqual(res_video.json()["format_type"], "video")

    def test_15_logout_and_revocation_lifecycle(self):
        """Assert POST /api/auth/logout invalidates session and subsequent protected calls return 401."""
        # Login
        res_login = self.client.post(
            "/api/auth/login",
            headers=self.remote_headers,
            json={"uid": self.server_uid, "password": self.server_password},
        )
        token = res_login.json()["session_token"]
        auth_headers = dict(self.remote_headers)
        auth_headers["Authorization"] = f"Bearer {token}"

        # Confirm access works initially
        self.assertEqual(self.client.get("/api/shared-folders", headers=auth_headers).status_code, 200)

        # Logout
        res_logout = self.client.post("/api/auth/logout", headers=auth_headers)
        self.assertEqual(res_logout.status_code, 200)
        self.assertTrue(res_logout.json().get("success"))

        # Subsequent calls must return 401
        self.assertEqual(
            self.client.get("/api/shared-folders", headers=auth_headers).status_code,
            401,
            "Revoked token still allowed access to /api/shared-folders",
        )
        self.assertEqual(
            self.client.post(
                "/api/queue",
                headers=auth_headers,
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            ).status_code,
            401,
            "Revoked token still allowed access to /api/queue",
        )

    def test_16_remote_workstation_security_wall(self):
        """Assert remote clients (even authenticated) receive 403 Forbidden on PC management endpoints."""
        # Login to obtain valid remote token
        res_login = self.client.post(
            "/api/auth/login",
            headers=self.remote_headers,
            json={"uid": self.server_uid, "password": self.server_password},
        )
        token = res_login.json()["session_token"]
        auth_headers = dict(self.remote_headers)
        auth_headers["Authorization"] = f"Bearer {token}"

        pc_restricted_endpoints = [
            ("GET", "/api/workstation/credentials", None),
            ("GET", "/api/workstation/settings", None),
            ("GET", "/api/workstation/info", None),
            ("GET", "/api/drives", None),
            ("GET", "/api/browse", None),
            ("POST", "/api/shared-folders", {"name": "Test", "path": "D:/Test"}),
            ("DELETE", "/api/shared-folders/B-Roll", None),
            ("POST", "/api/open-folder", {"path": "D:/Assets/BRoll"}),
        ]

        for method, endpoint, payload in pc_restricted_endpoints:
            if method == "POST":
                res = self.client.post(endpoint, headers=auth_headers, json=payload)
            elif method == "DELETE":
                res = self.client.delete(endpoint, headers=auth_headers)
            else:
                res = self.client.get(endpoint, headers=auth_headers)

            self.assertEqual(
                res.status_code,
                403,
                f"Remote call to workstation endpoint {endpoint} returned {res.status_code} instead of 403 Forbidden",
            )

    def test_17_remote_path_traversal_blocking(self):
        """Assert remote callers cannot supply custom filesystem paths even with valid auth."""
        res_login = self.client.post(
            "/api/auth/login",
            headers=self.remote_headers,
            json={"uid": self.server_uid, "password": self.server_password},
        )
        token = res_login.json()["session_token"]
        auth_headers = dict(self.remote_headers)
        auth_headers["Authorization"] = f"Bearer {token}"

        traversal_payloads = [
            {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "custom_path": "C:\\Windows\\System32"},
            {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "target_dir": "..\\..\\..\\"},
            {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "folder_key": "NonExistentPresetKey123"},
        ]

        for payload in traversal_payloads:
            reset_download_rate_limit(self.remote_ip)
            res = self.client.post("/api/queue", headers=auth_headers, json=payload)
            self.assertEqual(
                res.status_code,
                400,
                f"Payload {payload} was not blocked with 400 Bad Request (returned {res.status_code})",
            )

    def test_18_mobile_rate_limit_burst_defense(self):
        """Assert client submitting >10 jobs in 60s is throttled with HTTP 429 on the 11th request."""
        res_login = self.client.post(
            "/api/auth/login",
            headers=self.remote_headers,
            json={"uid": self.server_uid, "password": self.server_password},
        )
        token = res_login.json()["session_token"]
        auth_headers = dict(self.remote_headers)
        auth_headers["Authorization"] = f"Bearer {token}"

        reset_download_rate_limit(token)
        reset_download_rate_limit(self.remote_ip)

        # First 10 requests should succeed
        for i in range(10):
            res = self.client.post(
                "/api/queue",
                headers=auth_headers,
                json={
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "folder_key": "B-Roll (General)",
                },
            )
            self.assertEqual(res.status_code, 200, f"Request {i+1} failed with {res.status_code}")

        # 11th request must be rate-limited with 429
        res_11 = self.client.post(
            "/api/queue",
            headers=auth_headers,
            json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "folder_key": "B-Roll (General)",
            },
        )
        self.assertEqual(
            res_11.status_code,
            429,
            f"11th burst request returned {res_11.status_code} instead of 429 Too Many Requests",
        )
        reset_download_rate_limit(token)
        reset_download_rate_limit(self.remote_ip)

    def test_19_route_dispatcher_and_method_restriction(self):
        """Assert route dispatcher returns 200 for GET /mobile and 405 for write verbs."""
        # Parity check
        res_mob = self.client.get("/mobile")
        res_mob_html = self.client.get("/mobile.html")
        self.assertEqual(res_mob.status_code, 200)
        self.assertEqual(res_mob_html.status_code, 200)
        self.assertEqual(res_mob.content, res_mob_html.content)

        # Prohibit write verbs on /mobile
        for method in ["post", "put", "delete", "patch"]:
            res = getattr(self.client, method)("/mobile")
            self.assertEqual(res.status_code, 405)


if __name__ == "__main__":
    unittest.main()
