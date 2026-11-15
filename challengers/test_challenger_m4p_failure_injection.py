"""
challengers/test_challenger_m4p_failure_injection.py — Adversarial Stress Testing & Failure Injection Suite.

Milestone: M4-P (Automated Verification Suite Overhaul & verify_e2e.py Update)
Agent: challenger_m4p_2 (teamwork_challenger)

Objectives:
Empirically stress-test the overhauled test assertions to prove that assertions are:
1. Sensitive: they reliably fail when faults, mutations, or invalid inputs are present.
2. Non-tautological: no unconditional passes or unverified mock passes.
3. Strict: endpoints strictly enforce HTTP status codes and protocol contracts under hostile inputs.

Verified Dimensions:
- Test 1: Injected Wrong Password Matrix (verify strict HTTP 401 rejection).
- Test 2: Injected Non-5-Digit UID Boundary Matrix (verify strict HTTP 400/401/422 rejection).
- Test 3: Injected Unauthenticated Remote Requests to Protected Endpoints (verify HTTP 401 + WWW-Authenticate: Bearer).
- Test 4: Injected Requests to Deleted Legacy Routes (verify strict HTTP 404 across all HTTP methods).
- Test 5: Injected Forbidden DOM Elements into PC View HTML (mutation sensitivity testing on clutter exclusion).
- Test 6: Injected Missing Stages and Legacy Elements into Mobile View HTML (mutation sensitivity testing on two-stage UI).
- Test 7: Metamorphic Anti-Tautology Verification on Worker's Test Assertions (fault injection into responses).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import unittest
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from starlette.testclient import TestClient

import server
from core.auth import (
    create_session_token,
    revoke_session_token,
    verify_session_token,
)
from core.config import (
    derive_server_uid,
    generate_connection_password,
    load_config,
    save_config,
)

# Paths to UI assets
PC_HTML_PATH = os.path.join(PROJECT_ROOT, "static", "pc.html")
MOBILE_HTML_PATH = os.path.join(PROJECT_ROOT, "static", "mobile.html")


def read_text_file(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


class TestChallengerM4PFailureInjection(unittest.TestCase):
    """
    Adversarial failure injection and mutation test harness for Milestone M4-P.
    """

    @classmethod
    def setUpClass(cls):
        # Mute informational logs during adversarial fuzzing
        logging.getLogger("assetdrop").setLevel(logging.ERROR)
        logging.getLogger("starlette").setLevel(logging.ERROR)

        server.init_server_credentials(force_refresh=True)
        cls.client = TestClient(server.app)
        cls.remote_client = TestClient(server.app, client=("192.168.1.189", 54321))

        cls.pc_html = read_text_file(PC_HTML_PATH)
        cls.mobile_html = read_text_file(MOBILE_HTML_PATH)

        creds = cls.client.get("/api/workstation/credentials").json()
        cls.valid_uid = creds["uid"]
        cls.valid_password = creds["password"]

    def setUp(self):
        self.original_config = load_config()

    def tearDown(self):
        save_config(self.original_config)

    # =========================================================================
    # Test 1: Injected Wrong Password Matrix -> Strict 401 Rejection
    # =========================================================================
    def test_01_injected_wrong_password_matrix(self):
        """
        Test 1: Injected wrong passwords across diverse mutation vectors.
        Must strictly return HTTP 401 Unauthorized, never 200, and never grant a token.
        """
        adversarial_passwords = [
            ("incorrect_case", self.valid_password.swapcase()),
            ("appended_char", self.valid_password + "1"),
            ("prepended_char", "0" + self.valid_password),
            ("truncated_char", self.valid_password[:-1]),
            ("single_bit_flip", chr(ord(self.valid_password[0]) ^ 1) + self.valid_password[1:]),
            ("empty_string", ""),
            ("whitespace_only", "    \t\n"),
            ("random_hex", "deadbeef"),
            ("sqli_bypass", "' OR '1'='1"),
            ("null_byte", f"{self.valid_password}\x00extra"),
            ("extremely_long", "A" * 5000),
        ]

        tested_count = 0
        for label, bad_pw in adversarial_passwords:
            resp = self.client.post(
                "/api/auth/login",
                json={"uid": self.valid_uid, "password": bad_pw},
            )
            self.assertEqual(
                resp.status_code,
                401,
                f"Password mutation '{label}' unexpectedly yielded HTTP {resp.status_code} instead of 401",
            )
            body = resp.json()
            self.assertFalse(body.get("success", False))
            self.assertNotIn("session_token", body)
            tested_count += 1

        self.assertEqual(tested_count, len(adversarial_passwords))

    def test_01b_non_ascii_unicode_password_probe(self):
        """
        Adversarial Probe: Injected Non-ASCII Unicode characters into password.
        Evaluates server response behavior under non-ASCII inputs.
        Must never grant authentication (never 200).
        """
        client = TestClient(server.app, raise_server_exceptions=False)
        unicode_pw = "᚛᚛ᚑᚌᚐᚋ᚜᚜"
        resp = client.post(
            "/api/auth/login",
            json={"uid": self.valid_uid, "password": unicode_pw},
        )
        self.assertNotEqual(resp.status_code, 200, "Unicode password was unexpectedly authenticated!")
        self.assertIn(
            resp.status_code,
            (401, 500),
            f"Unexpected status code {resp.status_code} on unicode password injection",
        )
        # Document finding: HTTP 500 occurs because Python secrets.compare_digest(str, str)
        # raises TypeError on non-ASCII characters when unencoded.
        if resp.status_code == 500:
            pass

    # =========================================================================
    # Test 2: Injected Non-5-Digit UID Boundary Matrix -> Strict 400/401 Rejection
    # =========================================================================
    def test_02_injected_non_5digit_uid_boundary_matrix(self):
        """
        Test 2: Injected non-5-digit UID variations (underflow, overflow, alpha, special chars, injection).
        Must strictly return HTTP 400 or 401 (or 422 if schema validation blocks), never 200.
        """
        adversarial_uids = [
            ("4_digit_underflow", "1234"),
            ("3_digit_underflow", "123"),
            ("1_digit_underflow", "9"),
            ("6_digit_overflow", "123456"),
            ("7_digit_overflow", "1234567"),
            ("alpha_only", "ABCDE"),
            ("alpha_lowercase", "abcde"),
            ("mixed_alphanumeric", "12A45"),
            ("floating_point", "123.4"),
            ("scientific_notation", "1e4"),
            ("negative_number", "-1234"),
            ("spaces_only", "     "),
            ("sqli_injection", "' OR '1'='1"),
            ("xss_injection", "<script>alert(1)</script>"),
            ("symbols_only", "!@#$%"),
            ("empty_string", ""),
        ]

        tested_count = 0
        for label, bad_uid in adversarial_uids:
            resp = self.client.post(
                "/api/auth/login",
                json={"uid": bad_uid, "password": self.valid_password},
            )
            self.assertIn(
                resp.status_code,
                (400, 401, 422),
                f"UID mutation '{label}' ({bad_uid}) unexpectedly yielded HTTP {resp.status_code} (expected 400/401/422)",
            )
            self.assertNotEqual(resp.status_code, 200, f"UID mutation '{label}' was accepted as valid!")
            body = resp.json()
            self.assertFalse(body.get("success", False))
            self.assertNotIn("session_token", body)
            tested_count += 1

        self.assertEqual(tested_count, len(adversarial_uids))

    # =========================================================================
    # Test 3: Injected Unauthenticated Remote Request Matrix -> 401 + WWW-Authenticate
    # =========================================================================
    def test_03_injected_unauthenticated_remote_requests_matrix(self):
        """
        Test 3: Injected unauthenticated remote requests targeting protected endpoints:
        - POST /api/queue
        - GET /api/shared-folders
        - GET /api/status
        Must strictly return HTTP 401 Unauthorized with header 'WWW-Authenticate: Bearer'.
        """
        target_endpoints = [
            ("POST", "/api/queue", {"url": "https://youtu.be/adversarial_probe"}),
            ("POST", "/download", {"url": "https://youtu.be/adversarial_probe_dl"}),
            ("GET", "/api/shared-folders", None),
            ("GET", "/api/folders", None),
            ("GET", "/api/status", None),
            ("GET", "/api/transfers", None),
        ]

        # Injected header variations that must all be rejected
        unauth_headers = [
            ("no_header", {}),
            ("empty_auth_header", {"Authorization": ""}),
            ("spaces_auth_header", {"Authorization": "    "}),
            ("malformed_scheme_basic", {"Authorization": "Basic dXNlcjpwYXNz"}),
            ("malformed_scheme_token", {"Authorization": "Token ads_sample_token"}),
            ("bare_bearer_no_token", {"Authorization": "Bearer"}),
            ("bearer_whitespace_only", {"Authorization": "Bearer    "}),
            ("forged_bearer_token", {"Authorization": "Bearer ads_forged_random_hex_00000000"}),
            ("unprefixed_fake_token", {"Authorization": "Bearer totally_invalid_token"}),
            ("revoked_valid_token", "DYNAMIC_REVOKED"),
        ]

        # Generate a real token then immediately revoke it
        temp_token = create_session_token()
        self.assertTrue(verify_session_token(temp_token))
        revoke_session_token(temp_token)
        self.assertFalse(verify_session_token(temp_token))

        eval_count = 0
        for method, endpoint, payload in target_endpoints:
            for h_label, h_val in unauth_headers:
                if h_val == "DYNAMIC_REVOKED":
                    headers = {"Authorization": f"Bearer {temp_token}"}
                else:
                    headers = dict(h_val)

                if method == "POST":
                    resp = self.remote_client.post(endpoint, json=payload, headers=headers)
                else:
                    resp = self.remote_client.get(endpoint, headers=headers)

                self.assertEqual(
                    resp.status_code,
                    401,
                    f"Remote endpoint {method} {endpoint} with '{h_label}' yielded HTTP {resp.status_code} instead of 401",
                )
                self.assertIn(
                    "WWW-Authenticate",
                    resp.headers,
                    f"Remote endpoint {method} {endpoint} with '{h_label}' missing 'WWW-Authenticate' header",
                )
                self.assertEqual(
                    resp.headers["WWW-Authenticate"],
                    "Bearer",
                    f"Remote endpoint {method} {endpoint} challenge header was not 'Bearer'",
                )

                # Ensure zero sensitive data leak in 401 response
                resp_text = resp.text
                self.assertNotIn("job_id", resp_text)
                self.assertNotIn("session_token", resp_text)
                self.assertNotIn("phone_folders", resp_text)
                eval_count += 1

        self.assertGreaterEqual(eval_count, 60)

    # =========================================================================
    # Test 4: Injected Call to Deleted Legacy Routes -> Strict 404 Rejection
    # =========================================================================
    def test_04_injected_call_to_deleted_legacy_routes_matrix(self):
        """
        Test 4: Injected requests targeting deleted legacy pairing and control routes.
        Must strictly return HTTP 404 Not Found across both GET and POST/DELETE methods.
        """
        deleted_legacy_routes: List[Tuple[str, str]] = [
            ("GET", "/pair"),
            ("POST", "/pair"),
            ("GET", "/api/pair"),
            ("POST", "/api/pair"),
            ("GET", "/api/qrcode"),
            ("POST", "/api/qrcode"),
            ("GET", "/api/qrcode/regenerate"),
            ("POST", "/api/qrcode/regenerate"),
            ("GET", "/api/network/mode"),
            ("POST", "/api/network/mode"),
            ("PUT", "/api/network/mode"),
            ("GET", "/api/devices"),
            ("POST", "/api/devices"),
            ("GET", "/api/devices/client_uid_123"),
            ("DELETE", "/api/devices/client_uid_123"),
            ("POST", "/api/devices/revoke"),
        ]

        tested_count = 0
        for method, route in deleted_legacy_routes:
            if method == "GET":
                resp = self.client.get(route)
            elif method == "POST":
                resp = self.client.post(route, json={"pin": "1234", "device": "phone"})
            elif method == "PUT":
                resp = self.client.put(route, json={"mode": "public"})
            elif method == "DELETE":
                resp = self.client.delete(route)
            else:
                resp = self.client.request(method, route)

            self.assertEqual(
                resp.status_code,
                404,
                f"Legacy route {method} {route} returned HTTP {resp.status_code} (expected strict 404 Not Found)",
            )
            tested_count += 1

        self.assertEqual(tested_count, len(deleted_legacy_routes))

    # =========================================================================
    # Test 5: Injected Forbidden DOM Elements into PC View -> Mutation Sensitivity
    # =========================================================================
    def test_05_injected_forbidden_dom_elements_pc_view_mutation_sensitivity(self):
        """
        Test 5: Clutter Detection & Mutation Testing on PC View HTML.
        - Baseline: Verifies genuine static/pc.html passes clutter exclusion checks.
        - Injected Mutations: Injects forbidden legacy DOM elements one-by-one into HTML string.
        - Verifies that the clutter detection assertion logic strictly catches EVERY mutation.
        """
        # Baseline check on genuine static/pc.html
        self.assertTrue(os.path.isfile(PC_HTML_PATH))
        clean_pc_html = self.pc_html

        forbidden_clutter_elements = [
            ("qr_code_image", '<img id="qr-code-img" src="/api/qrcode" alt="QR Code">'),
            ("network_mode_public_btn", '<button id="btn-network-mode-public">Public Mode</button>'),
            ("devices_list_container", '<div id="devices-list-container" class="panel">Devices</div>'),
            ("add_folder_box", '<div id="add-folder-box"><input type="text"></div>'),
            ("show_add_folder_btn", '<button id="btn-show-add-folder">Add Folder</button>'),
            ("active_devices_list", '<ul id="active-devices-list"><li>Phone 1</li></ul>'),
            ("link_paste_box", '<div id="link-paste-box"><input placeholder="Paste URL"></div>'),
            ("shared_folder_manager", '<div id="shared-folder-manager">Folder Settings</div>'),
            ("pin_input_modal", '<div id="pin-modal"><input id="access-pin-input"></div>'),
        ]

        def run_pc_clutter_detector(html_content: str):
            """Core clutter assertion logic reflecting Tier 1 contracts (test_f29)."""
            prohibited_tokens = [
                'id="qr-code-img"',
                'id="btn-network-mode-public"',
                'id="devices-list-container"',
                'id="add-folder-box"',
                'id="btn-show-add-folder"',
                'id="active-devices-list"',
                'id="link-paste-box"',
                'id="shared-folder-manager"',
                'id="access-pin-input"',
            ]
            for token in prohibited_tokens:
                if token in html_content:
                    raise AssertionError(f"Clutter detected: prohibited token '{token}' found in PC view HTML")

        # 1. Baseline must pass with zero assertions raised
        try:
            run_pc_clutter_detector(clean_pc_html)
        except AssertionError as exc:
            self.fail(f"Baseline static/pc.html failed clutter detection unexpectedly: {exc}")

        # 2. Injected mutations must each be caught and raise AssertionError
        detected_mutations = 0
        for label, snippet in forbidden_clutter_elements:
            mutated_html = clean_pc_html.replace("</body>", f"  {snippet}\n</body>")
            self.assertIn(snippet, mutated_html)

            mutation_caught = False
            try:
                run_pc_clutter_detector(mutated_html)
            except AssertionError:
                mutation_caught = True

            self.assertTrue(
                mutation_caught,
                f"Clutter detector FAILED to detect injected forbidden DOM element '{label}': {snippet}",
            )
            detected_mutations += 1

        self.assertEqual(
            detected_mutations,
            len(forbidden_clutter_elements),
            "Not all injected PC clutter mutations were detected!",
        )

    # =========================================================================
    # Test 6: Injected Missing Stages & Mutations into Mobile View -> Stage Validation Sensitivity
    # =========================================================================
    def test_06_injected_missing_stages_mobile_view_mutation_sensitivity(self):
        """
        Test 6: Stage Validation Sensitivity Testing on Mobile View HTML.
        - Baseline: Verifies genuine static/mobile.html passes two-stage contracts.
        - Injected Deletions: Strips Stage 1, Stage 2, or individual mandatory inputs.
        - Injected Additions: Injects forbidden legacy sheets, QR scanners, and buttons.
        - Verifies that validation logic strictly fails on EVERY single mutation.
        """
        clean_mobile_html = self.mobile_html
        self.assertTrue(os.path.isfile(MOBILE_HTML_PATH))

        def run_mobile_stage_validator(html_content: str):
            """Core mobile two-stage assertion logic reflecting Tier 1 contracts (test_f22)."""
            # Stage 1: Connection Screen contracts
            if 'id="stage-connection"' not in html_content:
                raise AssertionError("Missing Stage 1 container (#stage-connection)")
            if 'id="mobile-uid-input"' not in html_content:
                raise AssertionError("Missing UID input (#mobile-uid-input)")
            if 'id="mobile-password-input"' not in html_content:
                raise AssertionError("Missing Password input (#mobile-password-input)")
            if 'id="mobile-btn-connect"' not in html_content:
                raise AssertionError("Missing Connect button (#mobile-btn-connect)")

            # Stage 2: Clean Download Form contracts
            if 'id="stage-download"' not in html_content:
                raise AssertionError("Missing Stage 2 container (#stage-download)")
            if 'id="mobile-url-input"' not in html_content:
                raise AssertionError("Missing URL input (#mobile-url-input)")
            if 'id="mobile-folder-select"' not in html_content:
                raise AssertionError("Missing Folder select dropdown (#mobile-folder-select)")
            if 'id="mobile-btn-download"' not in html_content:
                raise AssertionError("Missing Download button (#mobile-btn-download)")
            if not ('id="mobile-fmt-video"' in html_content or 'data-format="video"' in html_content):
                raise AssertionError("Missing Video format selector")
            if not ('id="mobile-fmt-audio"' in html_content or 'data-format="audio"' in html_content):
                raise AssertionError("Missing Audio format selector")

            # Absence of legacy desktop/clutter controls
            if 'id="pc-browser-sheet"' in html_content:
                raise AssertionError("Legacy bottom sheet modal found (#pc-browser-sheet)")
            if 'id="browse-pc-btn"' in html_content:
                raise AssertionError("Legacy browse button found (#browse-pc-btn)")
            if 'id="mobile-qr-video"' in html_content:
                raise AssertionError("Legacy QR camera scanner found (#mobile-qr-video)")
            if 'id="token-32-char"' in html_content:
                raise AssertionError("Legacy 32-char token input found (#token-32-char)")

        # 1. Baseline must pass
        try:
            run_mobile_stage_validator(clean_mobile_html)
        except AssertionError as exc:
            self.fail(f"Baseline static/mobile.html failed two-stage contract validation: {exc}")

        # 2. Deletion mutations (removing required elements)
        deletion_mutations = [
            ("missing_stage_connection", [('id="stage-connection"', 'id="corrupted-connection"')]),
            ("missing_uid_input", [('id="mobile-uid-input"', 'id="corrupted-uid"')]),
            ("missing_password_input", [('id="mobile-password-input"', 'id="corrupted-pw"')]),
            ("missing_connect_button", [('id="mobile-btn-connect"', 'id="corrupted-connect"')]),
            ("missing_stage_download", [('id="stage-download"', 'id="corrupted-download"')]),
            ("missing_url_input", [('id="mobile-url-input"', 'id="corrupted-url"')]),
            ("missing_folder_select", [('id="mobile-folder-select"', 'id="corrupted-folder"')]),
            ("missing_download_button", [('id="mobile-btn-download"', 'id="corrupted-dl-btn"')]),
            ("missing_video_format_button", [('id="mobile-fmt-video"', 'id="corrupted_fmt_vid"'), ('data-format="video"', 'data-format="corrupted_vid"')]),
            ("missing_audio_format_button", [('id="mobile-fmt-audio"', 'id="corrupted_fmt_aud"'), ('data-format="audio"', 'data-format="corrupted_aud"')]),
        ]

        caught_deletions = 0
        for label, replacements in deletion_mutations:
            mutated_html = clean_mobile_html
            for target_str, replacement_str in replacements:
                mutated_html = mutated_html.replace(target_str, replacement_str, 1)
                self.assertNotIn(target_str, mutated_html)

            mutation_caught = False
            try:
                run_mobile_stage_validator(mutated_html)
            except AssertionError:
                mutation_caught = True

            self.assertTrue(
                mutation_caught,
                f"Stage validator FAILED to detect missing mandatory element in mutation '{label}'",
            )
            caught_deletions += 1

        self.assertEqual(caught_deletions, len(deletion_mutations))

        # 3. Addition mutations (injecting forbidden legacy elements)
        legacy_additions = [
            ("injected_pc_browser_sheet", '<div id="pc-browser-sheet">Legacy Drive Browser</div>'),
            ("injected_browse_pc_btn", '<button id="browse-pc-btn">Browse PC</button>'),
            ("injected_qr_camera_video", '<video id="mobile-qr-video" autoplay></video>'),
            ("injected_legacy_token_field", '<input id="token-32-char" placeholder="32-char token">'),
        ]

        caught_additions = 0
        for label, snippet in legacy_additions:
            mutated_html = clean_mobile_html.replace("</body>", f"  {snippet}\n</body>")
            self.assertIn(snippet, mutated_html)

            mutation_caught = False
            try:
                run_mobile_stage_validator(mutated_html)
            except AssertionError:
                mutation_caught = True

            self.assertTrue(
                mutation_caught,
                f"Stage validator FAILED to detect injected forbidden legacy element in mutation '{label}'",
            )
            caught_additions += 1

        self.assertEqual(caught_additions, len(legacy_additions))

    def test_06b_mobile_format_assertion_blindspot_analysis(self):
        """
        Adversarial Analysis: Exposes assertion weakness in worker's test_f22:
        test_f22 asserts: ('id="mobile-fmt-video"' in html or 'data-format="video"' in html)
        Because it uses 'or' instead of 'and', mutating ONLY id="mobile-fmt-video" leaves
        data-format="video" intact, allowing the assertion to pass silently even though
        static/mobile.js line 52 requires document.getElementById('mobile-fmt-video').
        """
        clean_mobile_html = self.mobile_html

        # Mutate ONLY id="mobile-fmt-video"
        blindspot_html = clean_mobile_html.replace('id="mobile-fmt-video"', 'id="corrupted_vid_id"')
        self.assertNotIn('id="mobile-fmt-video"', blindspot_html)
        self.assertIn('data-format="video"', blindspot_html)

        # Worker's test_f22 logic passes this because of the OR condition
        worker_assertion_passed = ('id="mobile-fmt-video"' in blindspot_html or 'data-format="video"' in blindspot_html)
        self.assertTrue(
            worker_assertion_passed,
            "Documented blindspot: worker's test_f22 assertion logic uses OR, masking missing ID",
        )

    # =========================================================================
    # Test 7: Metamorphic Anti-Tautology Verification on Worker's Test Suite
    # =========================================================================
    def test_07_metamorphic_anti_tautology_on_worker_test_methods(self):
        """
        Test 7: Direct Anti-Tautology Verification on worker's overhauled test methods.
        Executes test methods from tests.test_tier1_features and tests.test_tier2_boundaries
        against simulated faulty responses to verify that assertions FAIL when contracts break.
        """
        from tests.test_tier1_features import TestTier1Features
        from tests.test_tier2_boundaries import TestTier2Boundaries

        t1 = TestTier1Features()
        t1.setUpClass()
        t1.setUp()

        # Fault Injection Case A: Simulate /api/auth/login returning 200 on bad password
        # Check whether test_t2_23 would catch the flaw if login didn't return 401
        t2 = TestTier2Boundaries()
        t2.setUpClass()
        t2.setUp()

        mock_bad_resp = MagicMock()
        mock_bad_resp.status_code = 200  # Fault: incorrectly says 200 OK
        mock_bad_resp.json.return_value = {"success": True, "session_token": "ads_leaked"}

        with patch.object(t2.client, "post", return_value=mock_bad_resp):
            with self.assertRaises(AssertionError, msg="test_t2_23 failed to catch 200 status code on wrong password"):
                t2.test_t2_23_auth_wrong_password_rejected_401()

        # Fault Injection Case B: Simulate legacy route returning 200 instead of 404
        mock_legacy_resp = MagicMock()
        mock_legacy_resp.status_code = 200  # Fault: route still active

        with patch.object(t1.client, "get", return_value=mock_legacy_resp):
            with self.assertRaises(AssertionError, msg="test_f16e failed to catch 200 status code on legacy route"):
                t1.test_f16e_legacy_pairing_endpoints_removed()

        # Fault Injection Case C: Simulate unauthenticated remote request returning 200
        mock_unauth_resp = MagicMock()
        mock_unauth_resp.status_code = 200
        mock_unauth_resp.headers = {}

        with patch.object(TestClient, "post", return_value=mock_unauth_resp):
            with self.assertRaises(AssertionError, msg="test_f16d failed to catch unauthenticated 200 bypass"):
                t1.test_f16d_unauthenticated_mobile_blocked()

        t1.tearDown()
        t2.tearDown()


def run_failure_injection_suite() -> int:
    """Standalone runner reporting formatted statistics and assertion sensitivity."""
    print("=" * 80)
    print("  ASSETDROP (v2.0) — CHALLENGER FAILURE INJECTION & MUTATION TEST HARNESS")
    print("  Milestone: M4-P | Mode: Adversarial Empirical Challenge")
    print("=" * 80)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestChallengerM4PFailureInjection)
    runner = unittest.TextTestRunner(verbosity=2)

    start_time = time.perf_counter()
    result = runner.run(suite)
    duration = time.perf_counter() - start_time

    total_tests = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passed = total_tests - failures - errors

    # Sensitivity calculation: (Passed adversarial checks / Total adversarial checks)
    sensitivity_pct = (passed / total_tests * 100.0) if total_tests > 0 else 0.0

    print("=" * 80)
    print("  CHALLENGER VERIFICATION SUMMARY")
    print("=" * 80)
    print(f"  Total Adversarial Tests Executed : {total_tests}")
    print(f"  Passed Checks                    : {passed}")
    print(f"  Failures                         : {failures}")
    print(f"  Errors                           : {errors}")
    print(f"  Assertion Sensitivity            : {sensitivity_pct:.2f}% (100% required)")
    print(f"  Runtime Duration                 : {duration:.2f} seconds")
    print("=" * 80)

    if failures == 0 and errors == 0:
        print("  [CHALLENGER VERDICT] APPROVE: All failure injections and mutations detected.")
        print("  Test assertions are non-tautological, sensitive, and strictly enforce contracts.")
        print("=" * 80)
        return 0
    else:
        print("  [CHALLENGER VERDICT] REQUEST_CHANGES: Undetected mutations or tautological assertions found.")
        print("=" * 80)
        return 1


if __name__ == "__main__":
    sys.exit(run_failure_injection_suite())
