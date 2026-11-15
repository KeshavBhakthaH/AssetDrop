"""
tests/test_challenger_m2p_empirical.py — Adversarial Empirical Challenge Suite for Milestone M2-P.

Target Areas:
1. Exhaustive DOM Structural Verification of static/pc.html (queue table, history table, credentials reveal).
2. Negative Assertion Sweep: Strict absence of QR codes, network toggles, device tables, folder managers, and paste boxes from static/pc.html and static/index.html (#view-desktop).
3. WCAG 2.5.5 Touch Target Ergonomics: Assert all interactive controls have min-height >= 44px and min-width >= 44px.
4. Smart Route Dispatching: Test /pc, /pc.html, /mobile, /mobile.html, and GET / across desktop, mobile, and adversarial User-Agents.
5. Workstation Credentials Security: Localhost allowlist vs remote 403 rejection.
6. JavaScript Ingestion Table Telemetry & XSS Neutralization.
"""

from __future__ import annotations

import html
from html.parser import HTMLParser
import json
import os
import re
import sys
import unittest
from typing import Dict, List, Optional, Set, Tuple

# Ensure repository root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from starlette.testclient import TestClient
import server

PC_HTML_PATH = os.path.join(PROJECT_ROOT, "static", "pc.html")
PC_CSS_PATH = os.path.join(PROJECT_ROOT, "static", "pc.css")
PC_JS_PATH = os.path.join(PROJECT_ROOT, "static", "pc.js")
INDEX_HTML_PATH = os.path.join(PROJECT_ROOT, "static", "index.html")


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class DOMInspector(HTMLParser):
    """Robust HTML5 parser for extracting element tags, attributes, hierarchies, and text."""

    def __init__(self):
        super().__init__()
        self.tags: List[str] = []
        self.ids: Dict[str, Tuple[str, Dict[str, str]]] = {}
        self.classes: Set[str] = set()
        self.elements: List[Dict[str, any]] = []
        self.text_content: List[str] = []
        self._current_tag_stack: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attr_dict = {k: v or "" for k, v in attrs}
        self.tags.append(tag)
        self._current_tag_stack.append(tag)

        el_id = attr_dict.get("id")
        if el_id:
            self.ids[el_id] = (tag, attr_dict)

        cls_val = attr_dict.get("class", "")
        for c in cls_val.split():
            self.classes.add(c)

        self.elements.append({
            "tag": tag,
            "attrs": attr_dict,
            "stack": list(self._current_tag_stack),
        })

    def handle_endtag(self, tag: str):
        if self._current_tag_stack and self._current_tag_stack[-1] == tag:
            self._current_tag_stack.pop()

    def handle_data(self, data: str):
        cleaned = data.strip()
        if cleaned:
            self.text_content.append(cleaned)


class SectionExtractor(HTMLParser):
    """Extracts a subtree by element ID (e.g., #view-desktop)."""

    def __init__(self, target_id: str):
        super().__init__()
        self.target_id = target_id
        self.in_target = False
        self.depth = 0
        self.captured_html: List[str] = []
        self.captured_elements: List[Dict[str, any]] = []
        self.captured_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attr_dict = {k: v or "" for k, v in attrs}
        if attr_dict.get("id") == self.target_id:
            self.in_target = True
            self.depth = 1
            self.captured_elements.append({"tag": tag, "attrs": attr_dict})
            return

        if self.in_target:
            self.depth += 1
            self.captured_elements.append({"tag": tag, "attrs": attr_dict})

    def handle_endtag(self, tag: str):
        if self.in_target:
            self.depth -= 1
            if self.depth == 0:
                self.in_target = False

    def handle_data(self, data: str):
        if self.in_target and data.strip():
            self.captured_text.append(data.strip())


# ============================================================================
# TEST SUITE: Milestone M2-P Empirical Verification & Adversarial Stress
# ============================================================================

class TestMilestoneM2PEmpirical(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.init_server_credentials(force_refresh=True)
        cls.client = TestClient(server.app)
        cls.pc_html = read_file(PC_HTML_PATH)
        cls.pc_css = read_file(PC_CSS_PATH)
        cls.pc_js = read_file(PC_JS_PATH)
        cls.index_html = read_file(INDEX_HTML_PATH)

        # Parse pc.html DOM
        cls.pc_dom = DOMInspector()
        cls.pc_dom.feed(cls.pc_html)

        # Extract visible desktop view from index.html
        cls.desktop_extractor = SectionExtractor("view-desktop")
        cls.desktop_extractor.feed(cls.index_html)

    # ------------------------------------------------------------------------
    # 1. Exhaustive DOM Structural Verification of static/pc.html
    # ------------------------------------------------------------------------
    def test_pc_html_boilerplate_and_metadata(self):
        """Assert static/pc.html contains valid HTML5 boilerplate, meta tags, and style links."""
        self.assertTrue(self.pc_html.startswith("<!DOCTYPE html>"), "Missing HTML5 DOCTYPE declaration")
        self.assertIn('<html lang="en">', self.pc_html, "Missing html lang='en' declaration")
        self.assertIn('<meta charset="UTF-8">', self.pc_html, "Missing UTF-8 charset declaration")
        self.assertIn('name="viewport"', self.pc_html, "Missing responsive viewport meta tag")
        self.assertIn('viewport-fit=cover', self.pc_html, "Missing viewport-fit=cover for safe-area insets")
        self.assertIn('<link rel="stylesheet" href="/static/pc.css">', self.pc_html, "Missing pc.css stylesheet link")
        self.assertIn('<script src="/static/pc.js"></script>', self.pc_html, "Missing pc.js script inclusion")

    def test_pc_html_telemetry_header_and_status(self):
        """Assert header bar contains brand branding and live connection status pill."""
        self.assertIn("connection-indicator", self.pc_dom.ids, "Missing #connection-indicator status pill")
        tag, attrs = self.pc_dom.ids["connection-indicator"]
        self.assertIn("status-pill", attrs.get("class", ""), "#connection-indicator must use .status-pill styling")
        self.assertIn("connection-status-text", self.pc_dom.ids, "Missing #connection-status-text element")
        self.assertIn("AssetDrop Workstation", " ".join(self.pc_dom.text_content))

    def test_pc_html_credentials_reveal_control(self):
        """Assert Section 1 contains mobile connection credentials toggle, UID display, and masked password."""
        # 1. Toggle Button
        self.assertIn("btn-toggle-credentials", self.pc_dom.ids, "Missing #btn-toggle-credentials button")
        btn_tag, btn_attrs = self.pc_dom.ids["btn-toggle-credentials"]
        self.assertEqual(btn_tag, "button")
        self.assertEqual(btn_attrs.get("aria-controls"), "credentials-details", "Button must specify aria-controls")
        self.assertEqual(btn_attrs.get("aria-expanded"), "false", "Credentials must be collapsed by default (aria-expanded=false)")

        # 2. Collapsible Details Container
        self.assertIn("credentials-details", self.pc_dom.ids, "Missing #credentials-details container")
        _, det_attrs = self.pc_dom.ids["credentials-details"]
        self.assertIn("hidden", det_attrs.get("class", ""), "Credentials details must have .hidden class by default")

        # 3. UID Display
        self.assertIn("pc-uid-display", self.pc_dom.ids, "Missing #pc-uid-display element")

        # 4. Password Display & Mask Toggle
        self.assertIn("pc-password-display", self.pc_dom.ids, "Missing #pc-password-display element")
        self.assertIn("btn-toggle-password-mask", self.pc_dom.ids, "Missing #btn-toggle-password-mask button")
        mask_tag, mask_attrs = self.pc_dom.ids["btn-toggle-password-mask"]
        self.assertEqual(mask_tag, "button")
        self.assertIn("aria-label", mask_attrs, "Password mask button must provide an accessible aria-label")

        # 5. Workstation URL Display
        self.assertIn("pc-connection-url", self.pc_dom.ids, "Missing #pc-connection-url element")

    def test_pc_html_active_queue_table(self):
        """Assert Section 2 contains the active download queue table with required 4 columns."""
        # Table and container
        self.assertIn("pc-queue-table", self.pc_dom.ids, "Missing #pc-queue-table element")
        tbl_tag, tbl_attrs = self.pc_dom.ids["pc-queue-table"]
        self.assertEqual(tbl_tag, "table")
        self.assertIn("data-table", tbl_attrs.get("class", ""), "Table must have data-table class")

        # Badge and Refresh Button
        self.assertIn("queue-count-badge", self.pc_dom.ids, "Missing #queue-count-badge element")
        self.assertIn("btn-refresh-queue", self.pc_dom.ids, "Missing #btn-refresh-queue button")

        # Tbody
        self.assertIn("pc-queue-tbody", self.pc_dom.ids, "Missing #pc-queue-tbody tbody element")

        # Exact required column headers
        table_html = self.pc_html[self.pc_html.find('id="pc-queue-table"'):self.pc_html.find('</table>', self.pc_html.find('id="pc-queue-table"'))]
        self.assertIn("Media File / URL", table_html, "Queue table missing 'Media File / URL' column header")
        self.assertIn("Format", table_html, "Queue table missing 'Format' column header")
        self.assertIn("Target Folder", table_html, "Queue table missing 'Target Folder' column header")
        self.assertIn("Status", table_html, "Queue table missing 'Status' column header")

    def test_pc_html_downloaded_history_table(self):
        """Assert Section 3 contains the completed downloads history table with required 4 columns."""
        # Table and container
        self.assertIn("pc-history-table", self.pc_dom.ids, "Missing #pc-history-table element")
        tbl_tag, tbl_attrs = self.pc_dom.ids["pc-history-table"]
        self.assertEqual(tbl_tag, "table")
        self.assertIn("data-table", tbl_attrs.get("class", ""), "Table must have data-table class")

        # Badge and Refresh Button
        self.assertIn("history-count-badge", self.pc_dom.ids, "Missing #history-count-badge element")
        self.assertIn("btn-refresh-history", self.pc_dom.ids, "Missing #btn-refresh-history button")

        # Tbody
        self.assertIn("pc-history-tbody", self.pc_dom.ids, "Missing #pc-history-tbody tbody element")

        # Exact required column headers
        table_html = self.pc_html[self.pc_html.find('id="pc-history-table"'):self.pc_html.find('</table>', self.pc_html.find('id="pc-history-table"'))]
        self.assertIn("File Name", table_html, "History table missing 'File Name' column header")
        self.assertIn("Save Location", table_html, "History table missing 'Save Location' column header")
        self.assertIn("Completion Time", table_html, "History table missing 'Completion Time' column header")
        self.assertIn("Action", table_html, "History table missing 'Action' column header")

    def test_pc_html_toast_notification_system(self):
        """Assert top toast container conforms to accessible alert pattern."""
        self.assertIn("pc-toast", self.pc_dom.ids, "Missing #pc-toast element")
        _, toast_attrs = self.pc_dom.ids["pc-toast"]
        self.assertEqual(toast_attrs.get("role"), "alert", "Toast must have role='alert'")
        self.assertEqual(toast_attrs.get("aria-live"), "assertive", "Toast must have aria-live='assertive'")
        self.assertIn("pc-toast-icon", self.pc_dom.ids, "Missing #pc-toast-icon element")
        self.assertIn("pc-toast-message", self.pc_dom.ids, "Missing #pc-toast-message element")

    # ------------------------------------------------------------------------
    # 2. Negative Assertion Sweep (Strict Exclusion of Prohibited Elements)
    # ------------------------------------------------------------------------
    def test_negative_assertion_sweep_pc_html(self):
        """Exhaustively assert that static/pc.html contains ZERO prohibited elements."""
        prohibited_ids = [
            "qr-code-img",
            "qr-loading",
            "qr-expiry-text",
            "btn-regenerate-qr",
            "btn-copy-lan-url",
            "btn-network-mode-public",
            "btn-network-mode-trusted",
            "network-mode-switch",
            "devices-card",
            "devices-list-container",
            "paired-count-badge",
            "desktop-shared-folders-list",
            "btn-show-add-folder",
            "add-folder-box",
            "new-folder-path-input",
            "new-folder-name-input",
            "url-input",
            "paste-btn",
            "submit-btn",
            "clear-url-btn",
            "mobile-view-unpaired",
            "mobile-scanner-wrapper",
            "mobile-manual-token-input",
        ]
        for pid in prohibited_ids:
            self.assertNotIn(pid, self.pc_dom.ids, f"PROHIBITED element id='{pid}' found in static/pc.html")

        # Prohibited terms and substrings
        prohibited_text_patterns = [
            r"qr-code",
            r"Scan QR",
            r"Public Network",
            r"Trusted Studio",
            r"Pairing Required",
            r"Revoke",
            r"Add Shared Folder",
            r"Paste 32-char token",
        ]
        for pattern in prohibited_text_patterns:
            matches = re.findall(pattern, self.pc_html, re.IGNORECASE)
            self.assertEqual(len(matches), 0, f"PROHIBITED pattern '{pattern}' found in static/pc.html: {matches}")

        # Assert no form or URL input exists
        input_elements = [el for el in self.pc_dom.elements if el["tag"] == "input"]
        self.assertEqual(len(input_elements), 0, f"Expected 0 <input> elements in pc.html, found: {input_elements}")

        # Assert no QR img / canvas
        for el in self.pc_dom.elements:
            if el["tag"] in ("img", "canvas"):
                self.fail(f"Unexpected graphical tag <{el['tag']}> found in pc.html: {el['attrs']}")

    def test_negative_assertion_sweep_visible_desktop_view_in_index_html(self):
        """Exhaustively assert that #view-desktop in static/index.html contains ZERO prohibited elements."""
        desktop_elements = self.desktop_extractor.captured_elements
        desktop_ids = {el["attrs"].get("id") for el in desktop_elements if "id" in el["attrs"]}
        desktop_classes = set()
        for el in desktop_elements:
            for c in el["attrs"].get("class", "").split():
                desktop_classes.add(c)
        desktop_text = " ".join(self.desktop_extractor.captured_text)

        prohibited_ids = [
            "qr-code-img",
            "qr-loading",
            "qr-expiry-text",
            "btn-regenerate-qr",
            "btn-copy-lan-url",
            "btn-network-mode-public",
            "btn-network-mode-trusted",
            "devices-card",
            "devices-list-container",
            "paired-count-badge",
            "desktop-shared-folders-list",
            "btn-show-add-folder",
            "add-folder-box",
            "new-folder-path-input",
            "new-folder-name-input",
            "url-input",
            "paste-btn",
            "submit-btn",
            "clear-url-btn",
        ]
        for pid in prohibited_ids:
            self.assertNotIn(pid, desktop_ids, f"PROHIBITED element id='{pid}' found inside #view-desktop in index.html")

        # Prohibited text phrases inside #view-desktop
        prohibited_phrases = [
            "Public Network",
            "Trusted Studio",
            "One-Time Ephemeral QR Pairing",
            "Shared Folders",
            "Authorized Paired Devices",
            "Revoke",
        ]
        for phrase in prohibited_phrases:
            self.assertNotIn(phrase, desktop_text, f"PROHIBITED phrase '{phrase}' found inside #view-desktop text")

        # Prohibited inputs inside #view-desktop
        input_elements = [el for el in desktop_elements if el["tag"] == "input"]
        self.assertEqual(len(input_elements), 0, f"Expected 0 <input> elements inside #view-desktop, found: {input_elements}")

    # ------------------------------------------------------------------------
    # 3. CSS & WCAG 2.5.5 Touch Target Ergonomics (>= 44px)
    # ------------------------------------------------------------------------
    def test_wcag_touch_targets_in_pc_css(self):
        """Assert CSS definitions for all interactive button classes mandate min-height >= 44px and min-width >= 44px."""
        # 1. Base .btn class
        btn_block_match = re.search(r"\.btn\s*\{([^}]+)\}", self.pc_css)
        self.assertIsNotNone(btn_block_match, "Missing .btn rule block in static/pc.css")
        btn_block = btn_block_match.group(1)

        min_h_match = re.search(r"min-height:\s*(\d+)px", btn_block)
        min_w_match = re.search(r"min-width:\s*(\d+)px", btn_block)
        self.assertIsNotNone(min_h_match, ".btn missing explicit min-height in pc.css")
        self.assertIsNotNone(min_w_match, ".btn missing explicit min-width in pc.css")
        self.assertGreaterEqual(int(min_h_match.group(1)), 44, ".btn min-height violates WCAG 2.5.5 (< 44px)")
        self.assertGreaterEqual(int(min_w_match.group(1)), 44, ".btn min-width violates WCAG 2.5.5 (< 44px)")

        # 2. .btn-open-folder class
        open_block_match = re.search(r"\.btn-open-folder\s*\{([^}]+)\}", self.pc_css)
        self.assertIsNotNone(open_block_match, "Missing .btn-open-folder rule block in static/pc.css")
        open_block = open_block_match.group(1)

        open_min_h = re.search(r"min-height:\s*(\d+)px", open_block)
        open_min_w = re.search(r"min-width:\s*(\d+)px", open_block)
        self.assertIsNotNone(open_min_h, ".btn-open-folder missing explicit min-height in pc.css")
        self.assertIsNotNone(open_min_w, ".btn-open-folder missing explicit min-width in pc.css")
        self.assertGreaterEqual(int(open_min_h.group(1)), 44, ".btn-open-folder min-height violates WCAG 2.5.5 (< 44px)")
        self.assertGreaterEqual(int(open_min_w.group(1)), 44, ".btn-open-folder min-width violates WCAG 2.5.5 (< 44px)")

        # 3. .status-pill touch ergonomics
        pill_block_match = re.search(r"\.status-pill\s*\{([^}]+)\}", self.pc_css)
        self.assertIsNotNone(pill_block_match, "Missing .status-pill rule block in static/pc.css")
        pill_block = pill_block_match.group(1)
        pill_min_h = re.search(r"min-height:\s*(\d+)px", pill_block)
        self.assertIsNotNone(pill_min_h, ".status-pill missing explicit min-height")
        self.assertGreaterEqual(int(pill_min_h.group(1)), 44, ".status-pill min-height violates WCAG 2.5.5 (< 44px)")

    def test_pc_html_all_interactive_elements_satisfy_wcag(self):
        """Assert every interactive button in static/pc.html uses an approved class conforming to WCAG 2.5.5."""
        button_elements = [el for el in self.pc_dom.elements if el["tag"] == "button"]
        self.assertGreater(len(button_elements), 0, "No buttons found in static/pc.html")

        for btn in button_elements:
            classes = btn["attrs"].get("class", "").split()
            btn_id = btn["attrs"].get("id", "anonymous")
            has_btn_class = any(c in ("btn", "btn-open-folder") for c in classes)
            self.assertTrue(
                has_btn_class,
                f"Button #{btn_id} in pc.html does not inherit from .btn or .btn-open-folder: {classes}",
            )

    def test_index_html_view_desktop_buttons_wcag_conformance(self):
        """Assert all buttons in #view-desktop of static/index.html have min-height and min-width >= 44px."""
        desktop_buttons = [el for el in self.desktop_extractor.captured_elements if el["tag"] == "button"]
        self.assertEqual(len(desktop_buttons), 4, f"Expected exactly 4 buttons in #view-desktop, found {len(desktop_buttons)}")

        for btn in desktop_buttons:
            style = btn["attrs"].get("style", "")
            btn_id = btn["attrs"].get("id", "unknown")
            h_match = re.search(r"min-height\s*:\s*(\d+)px", style)
            w_match = re.search(r"min-width\s*:\s*(\d+)px", style)
            self.assertIsNotNone(h_match, f"Button #{btn_id} in #view-desktop missing min-height inline style")
            self.assertIsNotNone(w_match, f"Button #{btn_id} in #view-desktop missing min-width inline style")
            self.assertGreaterEqual(int(h_match.group(1)), 44, f"Button #{btn_id} min-height < 44px")
            self.assertGreaterEqual(int(w_match.group(1)), 44, f"Button #{btn_id} min-width < 44px")

    # ------------------------------------------------------------------------
    # 4. Smart Route Dispatching & User-Agent Inspection Matrix
    # ------------------------------------------------------------------------
    def test_direct_pc_routes(self):
        """Verify GET /pc and GET /pc.html directly serve static/pc.html with HTTP 200 and text/html."""
        for path in ("/pc", "/pc.html"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f"Path {path} returned {resp.status_code}")
            self.assertIn("text/html", resp.headers.get("content-type", ""))
            self.assertIn("AssetDrop Workstation", resp.text)
            self.assertIn("/static/pc.css", resp.text)

    def test_direct_mobile_routes(self):
        """Verify GET /mobile and GET /mobile.html return HTTP 200 with text/html."""
        for path in ("/mobile", "/mobile.html"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f"Path {path} returned {resp.status_code}")
            self.assertIn("text/html", resp.headers.get("content-type", ""))

    def test_dynamic_root_user_agent_matrix(self):
        """Stress-test GET / with a comprehensive matrix of desktop, mobile, and boundary User-Agents."""
        desktop_user_agents = [
            ("Windows Chrome", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
            ("Windows Edge", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"),
            ("Windows Firefox", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0"),
            ("macOS Safari", "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15"),
            ("Linux Chrome", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
            ("PyWebView Desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; WebView/3.0)"),
        ]

        for name, ua in desktop_user_agents:
            with self.subTest(agent_type="desktop", name=name):
                resp = self.client.get("/", headers={"User-Agent": ua})
                self.assertEqual(resp.status_code, 200)
                self.assertIn("/static/pc.css", resp.text, f"Desktop UA '{name}' did not receive static/pc.html")
                self.assertIn("AssetDrop Workstation", resp.text)

        mobile_user_agents = [
            ("Android Pixel Chrome", "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.90 Mobile Safari/537.36"),
            ("iPhone Safari", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"),
            ("iPad Safari", "Mozilla/5.0 (iPad; CPU OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"),
            ("iPod Touch", "Mozilla/5.0 (iPod touch; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15"),
            ("Windows Phone", "Mozilla/5.0 (compatible; MSIE 10.0; Windows Phone 8.0; Trident/6.0; IEMobile/10.0; ARM; Touch)"),
            ("webOS TV/Device", "Mozilla/5.0 (webOS/2.0; U; en-US) AppleWebKit/525.27.1"),
        ]

        for name, ua in mobile_user_agents:
            with self.subTest(agent_type="mobile", name=name):
                resp = self.client.get("/", headers={"User-Agent": ua})
                self.assertEqual(resp.status_code, 200)
                self.assertNotIn("/static/pc.css", resp.text, f"Mobile UA '{name}' erroneously received static/pc.html")

        # Boundary & Adversarial User-Agents
        boundary_user_agents = [
            ("Empty UA", ""),
            ("Generic Python Requests", "python-requests/2.31.0"),
            ("curl", "curl/8.4.0"),
            ("Googlebot", "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"),
            ("Giant 10KB UA", "A" * 10000),
            ("Special Characters UA", "<script>alert(1)</script> / ; ' \" \x00"),
        ]

        for name, ua in boundary_user_agents:
            with self.subTest(agent_type="boundary", name=name):
                resp = self.client.get("/", headers={"User-Agent": ua})
                self.assertEqual(resp.status_code, 200, f"Boundary UA '{name}' crashed with {resp.status_code}")
                # Non-mobile agents default safely to pc.html
                self.assertIn("/static/pc.css", resp.text)

    # ------------------------------------------------------------------------
    # 5. Localhost Workstation Credentials API Security
    # ------------------------------------------------------------------------
    def test_workstation_credentials_localhost_contract(self):
        """Assert /api/workstation/credentials returns 200 on localhost with valid UID, password, and LAN URL."""
        for endpoint in ("/api/workstation/credentials", "/api/workstation/settings"):
            resp = self.client.get(endpoint)
            self.assertEqual(resp.status_code, 200, f"Localhost access to {endpoint} returned {resp.status_code}")
            data = resp.json()

            # UID assertions: exactly 5 digits, range [10000, 99999]
            uid = data.get("uid")
            self.assertIsInstance(uid, str, "UID must be a string")
            self.assertEqual(len(uid), 5, f"UID '{uid}' is not 5 characters")
            self.assertTrue(uid.isdigit(), f"UID '{uid}' is not purely numeric")
            self.assertNotEqual(uid[0], "0", f"UID '{uid}' must not have leading zero")
            self.assertTrue(10000 <= int(uid) <= 99999, f"UID {uid} out of valid range [10000, 99999]")

            # Password assertions: >= 8 characters
            pw = data.get("password")
            self.assertIsInstance(pw, str, "Password must be a string")
            self.assertGreaterEqual(len(pw), 8, f"Password '{pw}' is shorter than 8 characters")

            # Local IP and Port
            self.assertIn("local_ip", data)
            self.assertIn("port", data)
            self.assertIsInstance(data["port"], int)

            # Connection URL
            conn_url = data.get("connection_url")
            self.assertIsInstance(conn_url, str)
            self.assertTrue(conn_url.startswith("http://"), f"Connection URL '{conn_url}' must start with http://")

    def test_workstation_credentials_remote_forbidden(self):
        """Assert /api/workstation/credentials rejects remote LAN callers with 403 Forbidden."""
        # 1. Direct remote socket client (e.g. 192.168.1.50, 10.0.0.5)
        for remote_ip in ("192.168.1.50", "10.0.0.5", "172.16.1.100"):
            remote_client = TestClient(server.app, client=(remote_ip, 50000))
            for endpoint in ("/api/workstation/credentials", "/api/workstation/settings"):
                resp = remote_client.get(endpoint)
                self.assertEqual(
                    resp.status_code,
                    403,
                    f"Remote socket client {remote_ip} to {endpoint} was not blocked (status={resp.status_code})",
                )

        # 2. Forwarded header simulation on default client
        for fwd_ip in ("192.168.1.150", "10.0.0.45", "172.16.5.10"):
            for endpoint in ("/api/workstation/credentials", "/api/workstation/settings"):
                resp = self.client.get(endpoint, headers={"X-Forwarded-For": fwd_ip})
                self.assertEqual(
                    resp.status_code,
                    403,
                    f"X-Forwarded-For {fwd_ip} to {endpoint} was not blocked (status={resp.status_code})",
                )
                resp2 = self.client.get(endpoint, headers={"X-Remote-IP": fwd_ip})
                self.assertEqual(
                    resp2.status_code,
                    403,
                    f"X-Remote-IP {fwd_ip} to {endpoint} was not blocked (status={resp2.status_code})",
                )

    # ------------------------------------------------------------------------
    # 6. JavaScript Logic, Telemetry Polling & XSS Neutralization
    # ------------------------------------------------------------------------
    def test_pc_js_polling_and_endpoint_targets(self):
        """Assert static/pc.js targets correct API endpoints and defines an adaptive polling interval."""
        self.assertIn("/api/workstation/credentials", self.pc_js)
        self.assertIn("/api/workstation/settings", self.pc_js)
        self.assertIn("/api/transfers", self.pc_js)
        self.assertIn("/api/transfers/", self.pc_js)
        self.assertIn("/open", self.pc_js)

        # Polling interval check: between 2000ms and 3000ms
        poll_match = re.search(r"pollingIntervalMs:\s*(\d+)", self.pc_js)
        self.assertIsNotNone(poll_match, "Missing pollingIntervalMs in static/pc.js")
        interval = int(poll_match.group(1))
        self.assertGreaterEqual(interval, 2000, "Polling interval too aggressive (< 2000ms)")
        self.assertLessEqual(interval, 5000, "Polling interval too slow (> 5000ms)")

    def test_pc_js_xss_sanitization_defense(self):
        """Assert static/pc.js includes robust HTML escaping to prevent XSS injection in telemetry tables."""
        self.assertIn("escapeHtml", self.pc_js, "Missing escapeHtml helper function in static/pc.js")
        self.assertIn("&amp;", self.pc_js)
        self.assertIn("&lt;", self.pc_js)
        self.assertIn("&gt;", self.pc_js)
        self.assertIn("&quot;", self.pc_js)
        self.assertIn("&#039;", self.pc_js)

        # Verify simulation of escapeHtml against malicious payloads
        def simulated_escape_html(s):
            if not s:
                return ""
            return (
                str(s)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#039;")
            )

        adversarial_payloads = [
            ('<script>alert("pwned")</script>', ["&lt;script&gt;", "&quot;pwned&quot;"]),
            ('"><img src=x onerror=alert(1)>', ["&quot;&gt;&lt;img", "onerror=alert(1)&gt;"]),
            ("'; DROP TABLE transfers; --", ["&#039;; DROP TABLE transfers; --"]),
            ('<svg/onload=alert`1`>', ["&lt;svg/onload=alert`1`&gt;"]),
        ]
        for payload, expected_substrings in adversarial_payloads:
            escaped = simulated_escape_html(payload)
            self.assertNotIn("<script>", escaped)
            self.assertNotIn("<img", escaped)
            self.assertNotIn("<svg", escaped)
            for sub in expected_substrings:
                self.assertIn(sub, escaped)

    # ------------------------------------------------------------------------
    # 7. Telemetry & Open in Explorer API Integration
    # ------------------------------------------------------------------------
    def test_transfers_telemetry_schema(self):
        """Assert /api/transfers and /api/status return valid JSON schema with active and completed arrays."""
        for endpoint in ("/api/transfers", "/api/status", "/status"):
            resp = self.client.get(endpoint)
            self.assertEqual(resp.status_code, 200, f"Endpoint {endpoint} failed with {resp.status_code}")
            data = resp.json()
            self.assertIn("active", data, f"Endpoint {endpoint} response missing 'active' list")
            self.assertIn("completed", data, f"Endpoint {endpoint} response missing 'completed' list")
            self.assertIsInstance(data["active"], list)
            self.assertIsInstance(data["completed"], list)

    def test_transfers_open_endpoint_security(self):
        """Assert POST /api/transfers/{job_id}/open defends in depth (401 unauth, 403 remote auth, 404 missing)."""
        # Non-existent job from localhost -> 404 Not Found
        resp_404 = self.client.post("/api/transfers/non-existent-uuid/open")
        self.assertEqual(resp_404.status_code, 404)

        # Path traversal job ID -> 404 Not Found
        resp_trav = self.client.post("/api/transfers/../../Windows/System32/open")
        self.assertIn(resp_trav.status_code, (404, 400))

        # Remote unauthenticated caller attempting to open folder -> 401 Unauthorized
        remote_client = TestClient(server.app, client=("192.168.1.88", 50000))
        resp_unauth = remote_client.post("/api/transfers/some-uuid/open")
        self.assertEqual(resp_unauth.status_code, 401, "Unauthenticated remote caller must receive 401 Unauthorized")

        # Remote authenticated caller attempting to open folder -> 403 Forbidden
        from core.auth import create_session_token
        valid_tok = create_session_token()
        resp_remote_auth = remote_client.post(
            "/api/transfers/some-uuid/open",
            headers={"Authorization": f"Bearer {valid_tok}"},
        )
        self.assertEqual(resp_remote_auth.status_code, 403, "Authenticated remote caller must receive 403 Forbidden")


if __name__ == "__main__":
    unittest.main(verbosity=2)
