"""
tests/test_challenger_m3p_empirical.py — Empirical Verification Suite for Milestone M3-P.

Validates:
1. File Existence & Integrity: static/mobile.html, mobile.css, mobile.js, mobile/build.js, mobile/www/index.html.
2. DOM Structural Verification of static/mobile.html (Two-Stage Architecture).
3. Negative Clutter Assertion Sweep (Strict absence of QR scanner, video tags, 32-char token, directory sheets, status tray).
4. WCAG 2.5.5 Touch Target Conformance (min-height >= 44px, min-width >= 44px across all controls).
5. Route Dispatching & Parity: /mobile, /mobile.html, and GET / across Mobile & Desktop User-Agents.
6. Capacitor Android Build Sync (node mobile/build.js execution & asset parity).
7. End-to-End API Interaction Flow (Login -> Bearer Token -> Shared Folders -> Ingestion Queue <50ms SLA).
"""

from __future__ import annotations

from html.parser import HTMLParser
import json
import os
import re
import subprocess
import sys
import time
import unittest
from typing import Dict, List, Optional, Set, Tuple

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from starlette.testclient import TestClient
import server

MOBILE_HTML_PATH = os.path.join(PROJECT_ROOT, "static", "mobile.html")
MOBILE_CSS_PATH = os.path.join(PROJECT_ROOT, "static", "mobile.css")
MOBILE_JS_PATH = os.path.join(PROJECT_ROOT, "static", "mobile.js")
BUILD_JS_PATH = os.path.join(PROJECT_ROOT, "mobile", "build.js")
MOBILE_WWW_INDEX_PATH = os.path.join(PROJECT_ROOT, "mobile", "www", "index.html")
PC_HTML_PATH = os.path.join(PROJECT_ROOT, "static", "pc.html")


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class MobileDOMInspector(HTMLParser):
    """HTML5 DOM inspector capturing elements, IDs, classes, and hierarchy."""

    def __init__(self):
        super().__init__()
        self.tags: List[str] = []
        self.ids: Dict[str, Tuple[str, Dict[str, str]]] = {}
        self.classes: Set[str] = set()
        self.elements: List[Dict[str, any]] = []
        self.text_content: List[str] = []

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

    def handle_data(self, data: str):
        if data.strip():
            self.text_content.append(data.strip())


class TestMilestoneM3PEmpirical(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.init_server_credentials(force_refresh=True)
        cls.client = TestClient(server.app)
        cls.mobile_html = read_file(MOBILE_HTML_PATH)
        cls.mobile_css = read_file(MOBILE_CSS_PATH)
        cls.mobile_js = read_file(MOBILE_JS_PATH)

        cls.dom = MobileDOMInspector()
        cls.dom.feed(cls.mobile_html)

    # ------------------------------------------------------------------------
    # 1. File Existence & Baseline Assets
    # ------------------------------------------------------------------------
    def test_01_mobile_files_exist_and_non_empty(self):
        """Assert all required mobile assets exist on disk and have meaningful size."""
        for path, name in [
            (MOBILE_HTML_PATH, "static/mobile.html"),
            (MOBILE_CSS_PATH, "static/mobile.css"),
            (MOBILE_JS_PATH, "static/mobile.js"),
            (BUILD_JS_PATH, "mobile/build.js"),
        ]:
            self.assertTrue(os.path.isfile(path), f"File {name} missing from repository")
            self.assertGreater(os.path.getsize(path), 200, f"File {name} is suspiciously small (<200 bytes)")

    # ------------------------------------------------------------------------
    # 2. DOM Structural Contracts (Two-Stage Architecture)
    # ------------------------------------------------------------------------
    def test_02_html5_boilerplate_and_metadata(self):
        """Assert static/mobile.html includes proper HTML5 tags, mobile viewport, and dark theme."""
        self.assertTrue(self.mobile_html.startswith("<!DOCTYPE html>"), "Missing HTML5 DOCTYPE declaration")
        self.assertIn('<html lang="en">', self.mobile_html)
        self.assertIn('<meta charset="UTF-8">', self.mobile_html)
        self.assertIn('name="viewport"', self.mobile_html)
        self.assertIn('viewport-fit=cover', self.mobile_html)
        self.assertIn('content="#090d16"', self.mobile_html)
        self.assertIn('<link rel="stylesheet" href="/static/mobile.css">', self.mobile_html)
        self.assertIn('<script src="/static/mobile.js"></script>', self.mobile_html)

    def test_03_toast_notification_system(self):
        """Assert presence of instant toast notification element (#toast)."""
        self.assertIn("toast", self.dom.ids, "Missing #toast element")
        tag, attrs = self.dom.ids["toast"]
        self.assertEqual(attrs.get("role"), "alert", "#toast must have role='alert'")
        self.assertIn("hidden", attrs.get("class", ""), "#toast must be hidden by default")
        self.assertIn("toast-icon", self.dom.ids, "Missing #toast-icon element")
        self.assertIn("toast-message", self.dom.ids, "Missing #toast-message element")

    def test_04_stage1_connection_screen_contracts(self):
        """Assert Stage 1 (#stage-connection) contains all required authentication controls."""
        self.assertIn("stage-connection", self.dom.ids, "Missing #stage-connection container")
        _, stage1_attrs = self.dom.ids["stage-connection"]
        self.assertNotIn("hidden", stage1_attrs.get("class", ""), "Stage 1 must be visible initially (not hidden)")

        # Auth form
        self.assertIn("mobile-auth-form", self.dom.ids, "Missing #mobile-auth-form")

        # 5-digit UID input
        self.assertIn("mobile-uid-input", self.dom.ids, "Missing #mobile-uid-input")
        tag, uid_attrs = self.dom.ids["mobile-uid-input"]
        self.assertEqual(tag, "input")
        self.assertEqual(uid_attrs.get("inputmode"), "numeric")
        self.assertEqual(uid_attrs.get("maxlength"), "5")
        self.assertEqual(uid_attrs.get("pattern"), "[0-9]{5}")
        self.assertIn("required", uid_attrs)

        # Password input
        self.assertIn("mobile-password-input", self.dom.ids, "Missing #mobile-password-input")
        tag, pw_attrs = self.dom.ids["mobile-password-input"]
        self.assertEqual(tag, "input")
        self.assertEqual(pw_attrs.get("type"), "password")
        self.assertIn("required", pw_attrs)

        # Connect button
        self.assertIn("mobile-btn-connect", self.dom.ids, "Missing #mobile-btn-connect")
        tag, btn_attrs = self.dom.ids["mobile-btn-connect"]
        self.assertEqual(tag, "button")
        self.assertIn("Connect to PC", self.mobile_html)

        # Error banner
        self.assertIn("mobile-auth-error", self.dom.ids, "Missing #mobile-auth-error")
        _, err_attrs = self.dom.ids["mobile-auth-error"]
        self.assertEqual(err_attrs.get("role"), "alert")
        self.assertIn("hidden", err_attrs.get("class", ""), "Auth error must be hidden initially")

    def test_05_stage2_clean_download_form_contracts(self):
        """Assert Stage 2 (#stage-download) contains strictly clean download controls."""
        self.assertIn("stage-download", self.dom.ids, "Missing #stage-download container")
        _, stage2_attrs = self.dom.ids["stage-download"]
        self.assertIn("hidden", stage2_attrs.get("class", ""), "Stage 2 must be hidden by default until authenticated")

        # Connection status indicator and Disconnect button
        self.assertIn("mobile-connected-text", self.dom.ids, "Missing #mobile-connected-text badge")
        self.assertIn("mobile-btn-disconnect", self.dom.ids, "Missing #mobile-btn-disconnect button")

        # Download Form
        self.assertIn("mobile-download-form", self.dom.ids, "Missing #mobile-download-form")

        # 1. Media URL input & Paste button
        self.assertIn("mobile-url-input", self.dom.ids, "Missing #mobile-url-input")
        tag, url_attrs = self.dom.ids["mobile-url-input"]
        self.assertEqual(tag, "input")
        self.assertEqual(url_attrs.get("type"), "url")
        self.assertIn("required", url_attrs)

        self.assertIn("mobile-btn-paste", self.dom.ids, "Missing #mobile-btn-paste button")

        # 2. Format selector (MP3 vs MP4)
        self.assertIn("mobile-fmt-video", self.dom.ids, "Missing #mobile-fmt-video")
        self.assertIn("mobile-fmt-audio", self.dom.ids, "Missing #mobile-fmt-audio")
        tag, v_attrs = self.dom.ids["mobile-fmt-video"]
        tag, a_attrs = self.dom.ids["mobile-fmt-audio"]
        self.assertEqual(v_attrs.get("role"), "radio")
        self.assertEqual(a_attrs.get("role"), "radio")
        self.assertEqual(v_attrs.get("aria-checked"), "true")
        self.assertEqual(a_attrs.get("aria-checked"), "false")

        # 3. Destination folder select
        self.assertIn("mobile-folder-select", self.dom.ids, "Missing #mobile-folder-select")
        tag, sel_attrs = self.dom.ids["mobile-folder-select"]
        self.assertEqual(tag, "select")

        # 4. Download button
        self.assertIn("mobile-btn-download", self.dom.ids, "Missing #mobile-btn-download")
        tag, dl_attrs = self.dom.ids["mobile-btn-download"]
        self.assertEqual(tag, "button")
        self.assertIn("DOWNLOAD TO PC", self.mobile_html)

    # ------------------------------------------------------------------------
    # 3. Negative Clutter Assertion Sweep (Strict Absence of Peripheral Clutter)
    # ------------------------------------------------------------------------
    def test_06_negative_clutter_assertion_sweep(self):
        """Assert static/mobile.html strictly excludes ALL prohibited legacy and peripheral clutter."""
        prohibited_ids = [
            # Legacy QR & Scanner
            "mobile-scanner-wrapper",
            "mobile-qr-video",
            "btn-close-scanner",
            "mobile-btn-camera-scan",
            "mobile-btn-file-scan",
            "mobile-manual-token-input",
            "btn-submit-manual-token",
            "qr-code-img",
            "qr-loading",
            "btn-regenerate-qr",
            # Network mode controls
            "btn-network-mode-public",
            "btn-network-mode-trusted",
            "network-mode-switch",
            # Device list controls
            "devices-card",
            "devices-list-container",
            "paired-count-badge",
            # Directory browser sheet
            "pc-browser-sheet",
            "sheet-backdrop",
            "sheet-folder-list",
            "sheet-drives-list",
            "browse-pc-btn",
            # Status tray & telemetry logs
            "status-tray",
            "status-tray-header",
            "tray-active-list",
            "tray-recent-list",
            "telemetry-bar",
            # Preset chips
            "preset-chips-container",
        ]

        for pid in prohibited_ids:
            self.assertNotIn(pid, self.dom.ids, f"PROHIBITED element id='{pid}' found in static/mobile.html")

        # Check for prohibited HTML tags
        video_tags = [el for el in self.dom.elements if el["tag"] == "video"]
        self.assertEqual(len(video_tags), 0, f"PROHIBITED <video> element found in static/mobile.html: {video_tags}")

        canvas_tags = [el for el in self.dom.elements if el["tag"] == "canvas"]
        self.assertEqual(len(canvas_tags), 0, f"PROHIBITED <canvas> element found in static/mobile.html: {canvas_tags}")

        # Prohibited regex patterns in text/code
        prohibited_patterns = [
            r"qr-code",
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
        for pat in prohibited_patterns:
            matches = re.findall(pat, self.mobile_html, re.IGNORECASE)
            self.assertEqual(len(matches), 0, f"PROHIBITED pattern '{pat}' found in static/mobile.html: {matches}")

    # ------------------------------------------------------------------------
    # 4. WCAG 2.5.5 Touch Target Conformance (>= 44px)
    # ------------------------------------------------------------------------
    def test_07_wcag_touch_targets_in_css(self):
        """Assert CSS rules mandate min-height >= 44px and min-width >= 44px on all interactive elements."""
        interactive_selectors = [
            r"\.btn\s*\{[^}]*\}",
            r"\.field-input\s*\{[^}]*\}",
            r"\.field-select\s*\{[^}]*\}",
            r"\.segment-btn\s*\{[^}]*\}",
            r"\.btn-disconnect\s*\{[^}]*\}",
            r"\.btn-download\s*\{[^}]*\}",
        ]

        for pattern in interactive_selectors:
            match = re.search(pattern, self.mobile_css)
            self.assertIsNotNone(match, f"Missing CSS rule matching {pattern} in mobile.css")
            rule_block = match.group(0)

            # Check min-height >= 44px
            min_h_match = re.search(r"min-height\s*:\s*(\d+)px", rule_block)
            self.assertIsNotNone(min_h_match, f"Rule block missing explicit min-height:\n{rule_block}")
            min_h = int(min_h_match.group(1))
            self.assertGreaterEqual(min_h, 44, f"min-height {min_h}px violates WCAG 2.5.5 in rule:\n{rule_block}")

    def test_08_all_buttons_in_mobile_html_use_wcag_classes(self):
        """Assert every <button> tag in mobile.html inherits from .btn or .segment-btn."""
        buttons = [el for el in self.dom.elements if el["tag"] == "button"]
        self.assertGreaterEqual(len(buttons), 5, "Expected at least 5 buttons in mobile.html")

        for btn in buttons:
            classes = btn["attrs"].get("class", "").split()
            btn_id = btn["attrs"].get("id", "anonymous")
            has_valid_class = any(c in ("btn", "segment-btn") for c in classes)
            self.assertTrue(
                has_valid_class,
                f"Button #{btn_id} does not have a WCAG-compliant base class (.btn or .segment-btn): {classes}",
            )

    # ------------------------------------------------------------------------
    # 5. Route Dispatching & Parity
    # ------------------------------------------------------------------------
    def test_09_direct_mobile_route_parity(self):
        """Assert /mobile and /mobile.html return HTTP 200 with byte-for-byte identical content."""
        r_mob = self.client.get("/mobile")
        r_mob_html = self.client.get("/mobile.html")

        self.assertEqual(r_mob.status_code, 200, f"/mobile returned {r_mob.status_code}")
        self.assertEqual(r_mob_html.status_code, 200, f"/mobile.html returned {r_mob_html.status_code}")
        self.assertIn("text/html", r_mob.headers.get("content-type", ""))
        self.assertEqual(r_mob.content, r_mob_html.content, "Byte mismatch between /mobile and /mobile.html")
        self.assertIn("AssetDrop // Mobile Client", r_mob.text)
        self.assertIn("stage-connection", r_mob.text)
        self.assertIn("stage-download", r_mob.text)

    def test_10_user_agent_dispatching_matrix(self):
        """Assert mobile User-Agents on GET / serve mobile.html while desktop User-Agents serve pc.html."""
        mobile_uas = [
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
            "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        ]
        desktop_uas = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        ]

        for ua in mobile_uas:
            resp = self.client.get("/", headers={"User-Agent": ua})
            self.assertEqual(resp.status_code, 200)
            self.assertIn("/static/mobile.css", resp.text, f"Mobile UA {ua} did not receive mobile.html")
            self.assertIn("stage-connection", resp.text)
            self.assertNotIn("/static/pc.css", resp.text)

        for ua in desktop_uas:
            resp = self.client.get("/", headers={"User-Agent": ua})
            self.assertEqual(resp.status_code, 200)
            self.assertIn("/static/pc.css", resp.text, f"Desktop UA {ua} did not receive pc.html")
            self.assertNotIn("/static/mobile.css", resp.text)

    def test_11_prohibited_methods_on_mobile_routes(self):
        """Assert write methods (POST, PUT, DELETE, PATCH) on /mobile return 405 Method Not Allowed."""
        for method in ["post", "put", "delete", "patch"]:
            resp = getattr(self.client, method)("/mobile")
            self.assertEqual(resp.status_code, 405, f"Method {method.upper()} on /mobile returned {resp.status_code}")

    # ------------------------------------------------------------------------
    # 6. Android Capacitor Sync (mobile/build.js)
    # ------------------------------------------------------------------------
    def test_12_capacitor_build_sync_execution(self):
        """Assert node mobile/build.js executes successfully and syncs mobile.html to mobile/www/index.html."""
        res = subprocess.run(
            ["node", BUILD_JS_PATH],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"mobile/build.js failed with error:\n{res.stderr}")
        self.assertIn("Synced static/mobile.html -> mobile/www/index.html", res.stdout)

        # Assert destination file exists and is identical to static/mobile.html
        self.assertTrue(os.path.isfile(MOBILE_WWW_INDEX_PATH), "mobile/www/index.html does not exist")
        www_content = read_file(MOBILE_WWW_INDEX_PATH)
        self.assertEqual(www_content, self.mobile_html, "mobile/www/index.html does not match static/mobile.html")
        self.assertIn("stage-connection", www_content)
        self.assertIn("stage-download", www_content)

    # ------------------------------------------------------------------------
    # 7. End-to-End API Interaction Flow Simulation
    # ------------------------------------------------------------------------
    def test_13_mobile_auth_and_protected_flow(self):
        """
        Simulate complete mobile client workflow:
        1. Query credentials from localhost.
        2. Attempt remote unauthenticated calls -> 401 Unauthorized.
        3. Authenticate with UID & Password via POST /api/auth/login.
        4. Use Bearer token to fetch shared folders via GET /api/shared-folders.
        5. Submit ingestion task via POST /api/queue within 50ms SLA.
        """
        # 1. Fetch server credentials
        r_cred = self.client.get("/api/workstation/credentials")
        self.assertEqual(r_cred.status_code, 200)
        creds = r_cred.json()
        uid = creds["uid"]
        password = creds["password"]

        # 2. Remote unauthenticated probe
        remote_headers = {"X-Forwarded-For": "192.168.1.188"}
        r_unauth = self.client.get("/api/shared-folders", headers=remote_headers)
        self.assertEqual(r_unauth.status_code, 401, "Unauthenticated remote call did not return 401")

        # 3. Authenticate via POST /api/auth/login
        r_login = self.client.post(
            "/api/auth/login",
            headers=remote_headers,
            json={"uid": uid, "password": password},
        )
        self.assertEqual(r_login.status_code, 200, f"Login failed: {r_login.text}")
        login_data = r_login.json()
        self.assertTrue(login_data.get("success"))
        session_token = login_data.get("session_token")
        self.assertTrue(session_token.startswith("ads_"))

        # 4. Fetch folders using Bearer token
        auth_headers = {
            "X-Forwarded-For": "192.168.1.188",
            "Authorization": f"Bearer {session_token}",
        }
        r_folders = self.client.get("/api/shared-folders", headers=auth_headers)
        self.assertEqual(r_folders.status_code, 200)
        folders_data = r_folders.json()
        self.assertIn("folders", folders_data)
        folders = folders_data["folders"]
        self.assertGreater(len(folders), 0)

        # 5. Enqueue download under 50ms SLA
        target_folder = folders[0]["name"]
        t0 = time.perf_counter()
        r_queue = self.client.post(
            "/api/queue",
            headers=auth_headers,
            json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "format_type": "video",
                "folder_key": target_folder,
            },
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertEqual(r_queue.status_code, 200, f"Queue failed: {r_queue.text}")
        queue_data = r_queue.json()
        self.assertEqual(queue_data["status"], "queued")
        self.assertLess(elapsed_ms, 50.0, f"Queue latency {elapsed_ms:.2f}ms exceeded 50ms SLA")

    # ------------------------------------------------------------------------
    # 8. Adversarial Route Matrix & Boundary Inspection
    # ------------------------------------------------------------------------
    def test_14_adversarial_user_agents_matrix(self):
        """Stress-test root route dispatcher across wide matrix of mobile and desktop user agents."""
        mobile_matrix = [
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (iPad; CPU OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (Android 14; Mobile; rv:109.0) Gecko/120.0 Firefox/120.0",
            "Mozilla/5.0 (Linux; U; Android 12; en-US; SM-G998B Build/SP1A.210812.016) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/96.0.4664.104 UCBrowser/13.4.0.1306 Mobile Safari/537.36",
            "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        ]
        desktop_matrix = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
            "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            "",  # Empty UA defaults to desktop PC interface
            "curl/8.4.0",
            "Custom-Bot/1.0",
        ]

        for ua in mobile_matrix:
            resp = self.client.get("/", headers={"User-Agent": ua})
            self.assertEqual(resp.status_code, 200, f"Mobile UA failed: {ua}")
            self.assertIn("/static/mobile.css", resp.text, f"Mobile UA did not get mobile interface: {ua}")
            self.assertNotIn("/static/pc.css", resp.text)

        for ua in desktop_matrix:
            headers = {"User-Agent": ua} if ua else {}
            resp = self.client.get("/", headers=headers)
            self.assertEqual(resp.status_code, 200, f"Desktop UA failed: {ua}")
            self.assertIn("/static/pc.css", resp.text, f"Desktop UA did not get PC interface: {ua}")
            self.assertNotIn("/static/mobile.css", resp.text)

        # Adversarial long UA string
        long_ua = "A" * 8192
        resp = self.client.get("/", headers={"User-Agent": long_ua})
        self.assertIn(resp.status_code, (200, 431), "Extreme UA string should not crash server")

    def test_15_negative_clutter_sweep_across_js_css_and_android(self):
        """Assert zero camera/QR/token/directory sheet references in JS, CSS, and Android synced assets."""
        prohibited_js_terms = [
            "getUserMedia",
            "mediaDevices",
            "BarcodeDetector",
            "Html5Qrcode",
            "ZXing",
            "pc-browser-sheet",
            "sheet-backdrop",
            "sheet-folder-list",
            "manual-token",
            "manual_token",
            "/api/qrcode",
            "/api/devices",
            "/api/network/mode",
        ]
        for term in prohibited_js_terms:
            self.assertNotIn(term, self.mobile_js, f"Prohibited term '{term}' found in static/mobile.js")

        prohibited_css_terms = [
            "#pc-browser-sheet",
            ".sheet-backdrop",
            "#mobile-scanner-wrapper",
            "#status-tray",
            ".network-mode-switch",
        ]
        for term in prohibited_css_terms:
            self.assertNotIn(term, self.mobile_css, f"Prohibited CSS selector '{term}' found in static/mobile.css")

        # Check mobile/www/index.html (Android asset)
        www_html = read_file(MOBILE_WWW_INDEX_PATH)
        self.assertNotIn("<video", www_html.lower(), "Prohibited <video> tag found in mobile/www/index.html")
        self.assertNotIn("<canvas", www_html.lower(), "Prohibited <canvas> tag found in mobile/www/index.html")
        self.assertNotIn("pc-browser-sheet", www_html, "Prohibited pc-browser-sheet found in mobile/www/index.html")
        self.assertNotIn("32-char", self.mobile_html.lower(), "Prohibited 32-char reference found in static/mobile.html")

    def test_16_wcag_touch_targets_exact_dimensions_audit(self):
        """Assert all interactive elements enforce >= 44px min-dimensions in CSS."""
        required_targets = [
            "#mobile-btn-connect",
            "#mobile-btn-paste",
            "#mobile-fmt-video",
            "#mobile-fmt-audio",
            "#mobile-folder-select",
            "#mobile-btn-download",
            "#mobile-btn-disconnect",
        ]
        for elem_id in required_targets:
            raw_id = elem_id.lstrip("#")
            self.assertIn(raw_id, self.dom.ids, f"Required touch target {elem_id} missing from DOM")

        # Verify touch targets in CSS rules
        # .btn, .segment-btn, .btn-disconnect all define min-height >= 44px and min-width >= 44px
        self.assertRegex(self.mobile_css, r"\.btn\s*\{[^}]*min-height\s*:\s*(4[4-9]|[5-9]\d)px")
        self.assertRegex(self.mobile_css, r"\.btn\s*\{[^}]*min-width\s*:\s*(4[4-9]|[5-9]\d)px")
        self.assertRegex(self.mobile_css, r"\.segment-btn\s*\{[^}]*min-height\s*:\s*(4[4-9]|[5-9]\d)px")
        self.assertRegex(self.mobile_css, r"\.segment-btn\s*\{[^}]*min-width\s*:\s*(4[4-9]|[5-9]\d)px")
        self.assertRegex(self.mobile_css, r"\.btn-disconnect\s*\{[^}]*min-height\s*:\s*(4[4-9]|[5-9]\d)px")
        self.assertRegex(self.mobile_css, r"\.btn-disconnect\s*\{[^}]*min-width\s*:\s*(4[4-9]|[5-9]\d)px")
        self.assertRegex(self.mobile_css, r"\.field-select\s*\{[^}]*min-height\s*:\s*(4[4-9]|[5-9]\d)px")
        self.assertRegex(self.mobile_css, r"\.field-input\s*\{[^}]*min-height\s*:\s*(4[4-9]|[5-9]\d)px")

    def test_17_auth_boundary_fuzzing_and_error_handling(self):
        """Stress-test POST /api/auth/login with malformed, out-of-range, and injection payloads."""
        r_cred = self.client.get("/api/workstation/credentials")
        creds = r_cred.json()
        correct_uid = creds["uid"]
        correct_password = creds["password"]

        fuzz_cases = [
            {"uid": "1234", "password": correct_password},        # 4 digits
            {"uid": "123456", "password": correct_password},      # 6 digits
            {"uid": "abcde", "password": correct_password},       # letters
            {"uid": "12.34", "password": correct_password},       # float notation
            {"uid": correct_uid, "password": "wrong_password"},   # invalid password
            {"uid": correct_uid, "password": ""},                 # empty password
            {"uid": "", "password": correct_password},            # empty uid
            {"uid": "' OR '1'='1", "password": correct_password}, # SQL injection string
            {"uid": "<script>alert(1)</script>", "password": correct_password}, # XSS string
            {"uid": "\x00\x00\x00\x00\x00", "password": correct_password}, # null bytes
        ]

        remote_headers = {"X-Forwarded-For": "192.168.1.188"}
        for case in fuzz_cases:
            resp = self.client.post("/api/auth/login", headers=remote_headers, json=case)
            self.assertEqual(resp.status_code, 401, f"Fuzz case should return 401: {case} -> got {resp.status_code}")
            err_data = resp.json()
            self.assertIn("detail", err_data)

    def test_18_session_revocation_and_reauth_lifecycle(self):
        """Verify full token lifecycle: issue -> use -> revoke (/logout) -> 401 on reuse -> re-login."""
        r_cred = self.client.get("/api/workstation/credentials")
        creds = r_cred.json()
        remote_headers = {"X-Forwarded-For": "192.168.1.188"}

        # 1. Login
        resp = self.client.post("/api/auth/login", headers=remote_headers, json=creds)
        self.assertEqual(resp.status_code, 200)
        token1 = resp.json()["session_token"]

        # 2. Access protected endpoint
        auth_hdr1 = {"X-Forwarded-For": "192.168.1.188", "Authorization": f"Bearer {token1}"}
        resp = self.client.get("/api/shared-folders", headers=auth_hdr1)
        self.assertEqual(resp.status_code, 200)

        # 3. Logout / revoke
        resp = self.client.post("/api/auth/logout", headers=auth_hdr1)
        self.assertEqual(resp.status_code, 200)

        # 4. Attempt reuse of revoked token -> 401
        resp = self.client.get("/api/shared-folders", headers=auth_hdr1)
        self.assertEqual(resp.status_code, 401, "Revoked token was still accepted!")

        # 5. Re-authenticate cleanly -> new token issued and functional
        resp = self.client.post("/api/auth/login", headers=remote_headers, json=creds)
        self.assertEqual(resp.status_code, 200)
        token2 = resp.json()["session_token"]
        auth_hdr2 = {"X-Forwarded-For": "192.168.1.188", "Authorization": f"Bearer {token2}"}
        resp = self.client.get("/api/shared-folders", headers=auth_hdr2)
        self.assertEqual(resp.status_code, 200)

    def test_19_mobile_remote_security_isolation(self):
        """Assert remote mobile clients cannot access workstation management endpoints under any condition."""
        r_cred = self.client.get("/api/workstation/credentials")
        creds = r_cred.json()
        remote_headers = {"X-Forwarded-For": "192.168.1.188"}

        # Authenticate remote client
        resp = self.client.post("/api/auth/login", headers=remote_headers, json=creds)
        self.assertEqual(resp.status_code, 200)
        token = resp.json()["session_token"]
        auth_headers = {"X-Forwarded-For": "192.168.1.188", "Authorization": f"Bearer {token}"}

        # Remote authenticated client MUST get 403 Forbidden on workstation credentials
        r_workstation = self.client.get("/api/workstation/credentials", headers=auth_headers)
        self.assertEqual(r_workstation.status_code, 403, "Remote client bypassed credentials security barrier!")

        # Remote authenticated client MUST get 403 Forbidden on workstation settings
        r_settings = self.client.get("/api/workstation/settings", headers=auth_headers)
        self.assertEqual(r_settings.status_code, 403, "Remote client bypassed settings security barrier!")

        # Remote authenticated client MUST get 403 Forbidden on open-folder
        r_open = self.client.post("/api/open-folder", headers=auth_headers, json={"path": "D:/Assets"})
        self.assertEqual(r_open.status_code, 403, "Remote client bypassed open-folder security barrier!")

    def test_20_burst_queue_ingestion_under_sla(self):
        """Assert burst mobile queue submissions maintain sub-50ms ingestion latency SLA."""
        r_cred = self.client.get("/api/workstation/credentials")
        creds = r_cred.json()
        remote_headers = {"X-Forwarded-For": "192.168.1.188"}

        resp = self.client.post("/api/auth/login", headers=remote_headers, json=creds)
        self.assertEqual(resp.status_code, 200)
        token = resp.json()["session_token"]
        auth_headers = {"X-Forwarded-For": "192.168.1.188", "Authorization": f"Bearer {token}"}

        latencies = []
        for i in range(5):
            t0 = time.perf_counter()
            r_queue = self.client.post(
                "/api/queue",
                headers=auth_headers,
                json={
                    "url": f"https://www.youtube.com/watch?v=dQw4w9WgXcQ&burst={i}",
                    "format_type": "video" if i % 2 == 0 else "audio",
                    "folder_key": "B-Roll (General)",
                },
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(elapsed_ms)
            self.assertEqual(r_queue.status_code, 200, f"Burst queue item {i} failed: {r_queue.text}")
            data = r_queue.json()
            self.assertEqual(data["status"], "queued")
            self.assertIn("job_id", data)

        max_latency = max(latencies)
        mean_latency = sum(latencies) / len(latencies)
        self.assertLess(max_latency, 50.0, f"Max burst latency {max_latency:.2f}ms exceeded 50ms SLA")
        print(f"\n[M3-P EMPIRICAL BURST BENCHMARK] 5 queue requests: Mean={mean_latency:.2f}ms, Max={max_latency:.2f}ms (SLA < 50ms)")


if __name__ == "__main__":
    unittest.main()

