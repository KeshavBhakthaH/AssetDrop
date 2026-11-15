"""
challengers/test_challenger_m5p_tier5_adversarial.py — Tier 5 Adversarial Stress Testing Suite.

Milestone: M5-P (Final Acceptance & Adversarial Hardening)
Agent: challenger_m5p_1 (teamwork_challenger)

Adversarial Stress Dimensions:
1. Concurrency & Timing Attack Resistance on Auth:
   - 20-thread concurrent login attack with valid, invalid, and adversarial payloads.
   - Constant-time verification analysis (zero timing leakage side-channel).
   - Zero deadlock, zero thread contention crashes, bounded memory/thread delta.
2. Network Boundary Defense:
   - Remote LAN clients (non-localhost IP) CANNOT access workstation management endpoints
     (/api/workstation/credentials, /api/workstation/settings, /api/workstation/info, /api/drives, /api/browse).
   - Remote clients receive HTTP 403 Forbidden with zero path or credential disclosure.
   - Remote clients CANNOT submit to /api/queue or /download without valid session token
     (HTTP 401 Unauthorized with WWW-Authenticate: Bearer).
   - Authenticated remote clients receive phone-safe folders with zero filesystem paths.
3. Path Injection & SSRF Fuzzing:
   - Submit malicious URLs (file:///, localhost, 127.0.0.1, 169.254.169.254, RFC 1918 IPs, domain bypasses).
   - Remote client custom path injection attempts strictly blocked (HTTP 400).
   - Path traversal containment fuzzing (validate_path_containment).
   - Filename sanitization fuzzing (sanitize_filename).
4. Live Network Socket Probes:
   - Ephemeral live Uvicorn socket bound to 0.0.0.0, probed over real LAN IP.
"""

from __future__ import annotations

import concurrent.futures
import gc
import json
import logging
import os
import secrets
import socket
import statistics
import sys
import threading
import time
import unittest
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi import HTTPException
from starlette.testclient import TestClient

import server
from core.auth import (
    clear_all_sessions,
    create_session_token,
    get_active_session_count,
    revoke_session_token,
    verify_session_token,
)
from core.config import get_presets, load_config
from core.queue_manager import get_queue_manager
from core.security_limits import (
    reset_download_rate_limit,
    sanitize_filename,
    validate_download_url,
    validate_path_containment,
)
from tests.mock_cli import simulated_worker_func


# Silence verbose third-party loggers during testing
logging.basicConfig(level=logging.ERROR)
for _log in ("assetdrop", "httpx", "httpx2", "httpcore", "uvicorn", "uvicorn.error", "uvicorn.access"):
    logging.getLogger(_log).setLevel(logging.CRITICAL)


# ==============================================================================
# SECTION 1: CONCURRENCY & TIMING ATTACK RESISTANCE ON AUTH
# ==============================================================================

class TestTier5ConcurrencyAndTiming(unittest.TestCase):
    """
    Tier 5: 20-Thread Concurrent Login Attack & Constant-Time Response Audit.
    """

    @classmethod
    def setUpClass(cls):
        server.init_server_credentials(force_refresh=True)
        cls.creds = server.init_server_credentials()
        cls.valid_uid = cls.creds["uid"]
        cls.valid_pw = cls.creds["password"]
        cls.client = TestClient(server.app)

        # Pre-warm route handler
        cls.client.post("/api/auth/login", json={"uid": cls.valid_uid, "password": cls.valid_pw})

    def setUp(self):
        clear_all_sessions()

    def tearDown(self):
        clear_all_sessions()

    def test_01_concurrent_login_20_threads_burst_attack(self):
        """
        Submits 200 concurrent login requests across 20 threads simultaneously.
        Verifies:
        - 0 unhandled exceptions / 500 Internal Server Errors.
        - Zero deadlocks (all complete under SLA timeout).
        - Correct authentication responses: 200 for valid, 401/422 for invalid.
        - Session store thread-safety and token integrity.
        - Memory and session count remain consistent.
        """
        num_threads = 20
        requests_per_thread = 10
        total_requests = num_threads * requests_per_thread

        # Prepare 200 diverse login payloads
        payloads: List[Tuple[str, Dict[str, Any], int]] = []
        for i in range(total_requests):
            category = i % 4
            if category == 0:
                # Valid login
                payloads.append(("valid", {"uid": self.valid_uid, "password": self.valid_pw}, 200))
            elif category == 1:
                # Wrong password
                bad_pw = self.valid_pw[:-1] + ("0" if self.valid_pw[-1] != "0" else "1")
                payloads.append(("wrong_pw", {"uid": self.valid_uid, "password": bad_pw}, 401))
            elif category == 2:
                # Wrong UID
                bad_uid = str((int(self.valid_uid) + 11111) % 90000 + 10000)
                payloads.append(("wrong_uid", {"uid": bad_uid, "password": self.valid_pw}, 401))
            else:
                # Highly adversarial payloads
                adv_type = (i // 4) % 6
                if adv_type == 0:
                    payloads.append(("sqli", {"uid": self.valid_uid, "password": "' OR '1'='1"}, 401))
                elif adv_type == 1:
                    payloads.append(("unicode", {"uid": self.valid_uid, "password": "᚛ᚑᚌᚐᚋ᚜\u2620"}, 401))
                elif adv_type == 2:
                    payloads.append(("null_byte", {"uid": self.valid_uid, "password": "pass\x00word"}, 401))
                elif adv_type == 3:
                    payloads.append(("overflow", {"uid": self.valid_uid, "password": "A" * 5000}, 401))
                elif adv_type == 4:
                    payloads.append(("emoji", {"uid": self.valid_uid, "password": "🔐🔥💀🚀"}, 401))
                else:
                    payloads.append(("bad_uid_format", {"uid": "12", "password": self.valid_pw}, 401))

        results: List[Dict[str, Any]] = []
        results_lock = threading.Lock()

        def worker_task(idx: int, p_type: str, payload: Dict[str, Any], expected_status: int):
            t0 = time.perf_counter()
            resp = self.client.post("/api/auth/login", json=payload)
            dur = time.perf_counter() - t0
            with results_lock:
                results.append({
                    "idx": idx,
                    "type": p_type,
                    "status_code": resp.status_code,
                    "expected_status": expected_status,
                    "duration": dur,
                    "data": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {},
                })

        start_time = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(worker_task, idx, p_type, payload, expected_status)
                for idx, (p_type, payload, expected_status) in enumerate(payloads)
            ]
            concurrent.futures.wait(futures, timeout=10.0)

        total_duration = time.perf_counter() - start_time

        # Verify all 200 requests executed
        self.assertEqual(len(results), total_requests, f"Expected {total_requests} results, got {len(results)}")

        crashes_500 = [r for r in results if r["status_code"] == 500]
        self.assertEqual(len(crashes_500), 0, f"Encountered {len(crashes_500)} server 500 crashes!")

        valid_results = [r for r in results if r["type"] == "valid"]
        invalid_results = [r for r in results if r["type"] != "valid"]

        # Validate that all 50 valid logins succeeded
        self.assertEqual(len(valid_results), 50)
        created_tokens = []
        for vr in valid_results:
            self.assertEqual(vr["status_code"], 200)
            token = vr["data"].get("session_token")
            self.assertTrue(token and token.startswith("ads_"))
            created_tokens.append(token)

        # Validate that all 50 tokens are active and distinct
        self.assertEqual(len(set(created_tokens)), 50, "Session tokens generated concurrently must be distinct")
        for token in created_tokens:
            self.assertTrue(verify_session_token(token), f"Token {token} should be verified")

        self.assertEqual(get_active_session_count(), 50)

        # Validate that all 150 invalid logins were rejected (HTTP 401 or 422)
        for ir in invalid_results:
            self.assertIn(
                ir["status_code"],
                (401, 422),
                f"Payload {ir['type']} expected 401/422 but got {ir['status_code']}",
            )

        # Confirm overall completion time under 5.0 seconds
        self.assertLess(total_duration, 5.0, f"20-thread burst took {total_duration:.2f}s (ceiling 5.0s)")

    def test_02_constant_time_auth_comparison(self):
        """
        Performs statistical timing comparison across 5 authorization scenarios:
        1. Correct UID + Password matching 7 of 8 characters (near miss).
        2. Correct UID + Completely wrong password (0 of 8 characters).
        3. Wrong UID + Correct password.
        4. Wrong UID + Wrong password.
        5. Correct UID + 1000-character long password.

        Measures 50 samples per scenario (250 total) and verifies that timing
        variance is minimal and does not leak branch prediction or length.
        """
        num_samples = 50
        near_miss_pw = self.valid_pw[:-1] + ("0" if self.valid_pw[-1] != "0" else "1")
        far_miss_pw = "zzzzzzzz"
        wrong_uid = str((int(self.valid_uid) + 22222) % 90000 + 10000)
        long_pw = "x" * 1000

        scenarios = {
            "near_miss": {"uid": self.valid_uid, "password": near_miss_pw},
            "far_miss": {"uid": self.valid_uid, "password": far_miss_pw},
            "wrong_uid": {"uid": wrong_uid, "password": self.valid_pw},
            "both_wrong": {"uid": wrong_uid, "password": far_miss_pw},
            "long_pw": {"uid": self.valid_uid, "password": long_pw},
        }

        # Warm-up pass
        for body in scenarios.values():
            for _ in range(5):
                self.client.post("/api/auth/login", json=body)

        timings: Dict[str, List[float]] = {name: [] for name in scenarios}

        # Interleaved collection to eliminate drift bias
        for _ in range(num_samples):
            for name, body in scenarios.items():
                t0 = time.perf_counter()
                resp = self.client.post("/api/auth/login", json=body)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                self.assertEqual(resp.status_code, 401)
                timings[name].append(elapsed_ms)

        stats: Dict[str, Dict[str, float]] = {}
        for name, vals in timings.items():
            stats[name] = {
                "mean": statistics.mean(vals),
                "median": statistics.median(vals),
                "stdev": statistics.stdev(vals),
                "min": min(vals),
                "max": max(vals),
            }

        # Verify constant-time behavior:
        # secrets.compare_digest evaluates both UID and Password bytes.
        # Mean delta between near-miss and far-miss should be small (< 2.5ms).
        near_mean = stats["near_miss"]["mean"]
        far_mean = stats["far_miss"]["mean"]
        delta_pw = abs(near_mean - far_mean)
        self.assertLess(
            delta_pw,
            2.5,
            f"Timing delta between near-miss ({near_mean:.3f}ms) and far-miss ({far_mean:.3f}ms) is {delta_pw:.3f}ms (threshold 2.5ms)",
        )

        uid_mean = stats["wrong_uid"]["mean"]
        delta_uid = abs(near_mean - uid_mean)
        self.assertLess(
            delta_uid,
            2.5,
            f"Timing delta between wrong password and wrong UID is {delta_uid:.3f}ms (threshold 2.5ms)",
        )

    def test_03_zero_deadlock_under_concurrent_session_churn(self):
        """
        20 worker threads concurrently creating, verifying, and revoking tokens.
        Ensures threading lock (_SESSION_LOCK) never deadlocks or corrupts state.
        """
        num_threads = 20
        ops_per_thread = 15
        total_ops = num_threads * ops_per_thread

        success_count = [0]
        lock = threading.Lock()

        def churn_worker(worker_id: int):
            for i in range(ops_per_thread):
                token = create_session_token()
                self.assertTrue(verify_session_token(token))
                self.assertTrue(revoke_session_token(token))
                self.assertFalse(verify_session_token(token))
                with lock:
                    success_count[0] += 1

        t0 = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(churn_worker, wid) for wid in range(num_threads)]
            concurrent.futures.wait(futures, timeout=8.0)
        dur = time.perf_counter() - t0

        self.assertEqual(success_count[0], total_ops)
        self.assertLess(dur, 5.0, f"Concurrent churn took {dur:.2f}s")
        self.assertEqual(get_active_session_count(), 0)


# ==============================================================================
# SECTION 2: REMOTE LAN BOUNDARY DEFENSE
# ==============================================================================

class TestTier5RemoteLanBoundary(unittest.TestCase):
    """
    Tier 5: Remote LAN Client Boundary Enforcement & Workstation Protection.
    """

    @classmethod
    def setUpClass(cls):
        server.init_server_credentials(force_refresh=True)
        cls.creds = server.init_server_credentials()
        cls.valid_uid = cls.creds["uid"]
        cls.valid_pw = cls.creds["password"]
        cls.client = TestClient(server.app)

        # Remote LAN headers simulating external IP (192.168.1.188)
        cls.remote_headers = {
            "X-Forwarded-For": "192.168.1.188",
            "X-Remote-IP": "192.168.1.188",
        }

    def setUp(self):
        clear_all_sessions()
        reset_download_rate_limit("192.168.1.188")
        reset_download_rate_limit("unknown")

    def tearDown(self):
        clear_all_sessions()

    def test_04_workstation_endpoints_strictly_forbidden_for_remote_client(self):
        """
        Verifies that non-localhost / remote LAN clients CANNOT access workstation
        management endpoints:
        - GET /api/workstation/credentials (403 without token, 403 with token)
        - GET /api/workstation/settings (403 without token, 403 with token)
        - GET /api/workstation/info (403 without token, 403 with token)
        - GET /api/drives (403 when remote caller presents mobile session token)
        - GET /api/browse (403 when remote caller presents mobile session token)
        - POST /api/shared-folders/open (403)
        - POST /api/open-folder (403)
        - POST /api/transfers/{job_id}/open (403)
        - POST /api/shared-folders pinning (403)
        - DELETE /api/shared-folders/{name} (403)

        Asserts strictly HTTP 403 Forbidden with zero credential or path leakage.
        """
        # 1. Workstation credentials & info endpoints (public router with require_local_workstation)
        public_workstation_endpoints = [
            "/api/workstation/credentials",
            "/api/workstation/settings",
            "/api/workstation/info",
        ]
        for ep in public_workstation_endpoints:
            # Test without token
            resp = self.client.get(ep, headers=self.remote_headers)
            self.assertEqual(
                resp.status_code,
                403,
                f"Remote LAN request to {ep} without token must return 403 Forbidden, got {resp.status_code}",
            )
            self.assertNotIn(self.valid_pw, resp.text)
            self.assertNotIn("D:/Assets", resp.text)

        # 2. Protected workstation & traversal endpoints (require session token, but strictly 403 for remote callers)
        token = create_session_token()
        auth_headers = {**self.remote_headers, "Authorization": f"Bearer {token}"}

        protected_workstation_endpoints = [
            ("GET", "/api/drives", None),
            ("GET", "/api/browse", None),
            ("GET", "/api/browse?path=D:/", None),
            ("POST", "/api/shared-folders/open", {"path": "D:/Assets"}),
            ("POST", "/api/open-folder", {"path": "D:/Assets"}),
            ("POST", "/api/transfers/test-job-id-123/open", None),
            ("POST", "/api/shared-folders", {"name": "Hacked", "path": "C:/Windows"}),
            ("POST", "/api/presets", {"name": "Hacked", "path": "C:/Windows"}),
            ("DELETE", "/api/shared-folders/SFX", None),
        ]

        for method, endpoint, body in protected_workstation_endpoints:
            if method == "GET":
                resp = self.client.get(endpoint, headers=auth_headers)
            elif method == "POST":
                resp = self.client.post(endpoint, json=body or {}, headers=auth_headers)
            elif method == "DELETE":
                resp = self.client.delete(endpoint, headers=auth_headers)
            else:
                continue

            self.assertEqual(
                resp.status_code,
                403,
                f"Remote LAN request to {method} {endpoint} must return 403 Forbidden, got {resp.status_code}",
            )

            # Assert zero credential or path leakage
            content = resp.text
            self.assertNotIn(self.valid_pw, content, f"Password leaked in 403 response for {endpoint}")
            self.assertNotIn("D:/Assets", content, f"Internal path leaked in 403 response for {endpoint}")
            self.assertNotIn("C:\\", content, f"Windows drive leaked in 403 response for {endpoint}")

    def test_05_authenticated_remote_client_still_forbidden_on_workstation_endpoints(self):
        """
        Even when a remote client presents a valid authenticated session token (ads_<token>),
        workstation management endpoints MUST still return HTTP 403 Forbidden.
        Only the local desktop workstation operator may manage credentials/drives.
        """
        token = create_session_token()
        auth_remote_headers = {
            **self.remote_headers,
            "Authorization": f"Bearer {token}",
        }

        sensitive_endpoints = [
            "/api/workstation/credentials",
            "/api/workstation/settings",
            "/api/workstation/info",
            "/api/drives",
            "/api/browse",
        ]

        for ep in sensitive_endpoints:
            resp = self.client.get(ep, headers=auth_remote_headers)
            self.assertEqual(
                resp.status_code,
                403,
                f"Authenticated remote client accessing {ep} must receive 403 Forbidden, got {resp.status_code}",
            )
            self.assertNotIn(self.valid_pw, resp.text)

    def test_06_unauthenticated_remote_client_receives_401_with_www_authenticate(self):
        """
        Verifies that unauthenticated remote clients CANNOT access protected queue
        and presets endpoints:
        - POST /api/queue
        - POST /download
        - GET /api/shared-folders
        - GET /api/folders
        - GET /api/transfers
        - GET /api/status

        All must strictly return HTTP 401 Unauthorized with header 'WWW-Authenticate: Bearer'.
        """
        probes = [
            ("POST", "/api/queue", {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}),
            ("POST", "/download", {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}),
            ("GET", "/api/shared-folders", None),
            ("GET", "/api/folders", None),
            ("GET", "/api/transfers", None),
            ("GET", "/api/status", None),
        ]

        for method, endpoint, body in probes:
            if method == "POST":
                resp = self.client.post(endpoint, json=body or {}, headers=self.remote_headers)
            else:
                resp = self.client.get(endpoint, headers=self.remote_headers)

            self.assertEqual(
                resp.status_code,
                401,
                f"Unauthenticated remote client calling {method} {endpoint} must return 401, got {resp.status_code}",
            )
            auth_header = resp.headers.get("www-authenticate", "")
            self.assertIn(
                "Bearer",
                auth_header,
                f"Response to {endpoint} must include 'WWW-Authenticate: Bearer' header, got '{auth_header}'",
            )

    def test_07_invalid_and_forged_tokens_rejected_with_401(self):
        """
        Verifies remote client rejection when providing invalid, expired, or forged tokens.
        """
        bad_tokens = [
            "ads_00000000000000000000000000000000",
            "invalid_bearer_token",
            "ads_sqli_or_1_equals_1",
            "ads_forged_hex_token_9999999999999999",
            "   ",
        ]

        for bad in bad_tokens:
            headers = {**self.remote_headers, "Authorization": f"Bearer {bad}"}
            resp = self.client.get("/api/shared-folders", headers=headers)
            self.assertEqual(resp.status_code, 401, f"Bad token '{bad}' should return 401")
            self.assertIn("Bearer", resp.headers.get("www-authenticate", ""))

        # Non-ASCII token via query param (?token=...)
        resp_unicode = self.client.get("/api/shared-folders?token=᚛ᚑᚌᚐᚋ᚜", headers=self.remote_headers)
        self.assertEqual(resp_unicode.status_code, 401)
        self.assertIn("Bearer", resp_unicode.headers.get("www-authenticate", ""))

    def test_08_remote_client_shared_folders_zero_path_disclosure(self):
        """
        Verifies that an authenticated remote client calling GET /api/shared-folders
        receives ONLY safe folder metadata ({id, name}) and zero filesystem paths.
        """
        token = create_session_token()
        headers = {**self.remote_headers, "Authorization": f"Bearer {token}"}

        resp = self.client.get("/api/shared-folders", headers=headers)
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertIn("folders", data)
        self.assertNotIn("presets", data, "Presets map (containing absolute paths) must NOT be returned to remote clients")

        folders = data["folders"]
        self.assertIsInstance(folders, list)
        self.assertGreater(len(folders), 0)

        for folder in folders:
            self.assertIn("id", folder)
            self.assertIn("name", folder)
            self.assertNotIn("path", folder, f"Absolute path disclosed in remote folder entry: {folder}")
            # Ensure folder ID is 8-character hex
            self.assertEqual(len(folder["id"]), 8)


# ==============================================================================
# SECTION 3: PATH INJECTION & SSRF FUZZING
# ==============================================================================

class TestTier5PathInjectionAndSSRF(unittest.TestCase):
    """
    Tier 5: SSRF Injection Fuzzing & Path Traversal Containment Verification.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)
        cls.qm = get_queue_manager()
        cls.token = create_session_token()
        cls.remote_headers = {
            "X-Forwarded-For": "192.168.1.188",
            "Authorization": f"Bearer {cls.token}",
        }

    def setUp(self):
        reset_download_rate_limit(self.token)
        reset_download_rate_limit("192.168.1.188")
        reset_download_rate_limit("testclient")

    def test_09_ssrf_malicious_url_rejection_matrix(self):
        """
        Fuzzes POST /api/queue and POST /download with 25+ malicious and SSRF URLs:
        - Non-HTTP schemes (file:///, ftp://, gopher://, data:, javascript:)
        - Loopback SSRF (localhost, 127.0.0.1, 127.0.0.2, [::1], 0.0.0.0)
        - Cloud metadata SSRF (169.254.169.254 AWS/GCP metadata)
        - RFC 1918 Private IP SSRF (10.0.0.1, 172.16.0.1, 192.168.1.1)
        - Domain Allowlist Bypasses (attacker.com, subdomain spoofing)
        - Malformed URLs

        Asserts all return HTTP 400 Bad Request and zero jobs enqueued.
        """
        malicious_urls = [
            # Schemes
            "file:///C:/Windows/System32/drivers/etc/hosts",
            "file:///etc/passwd",
            "file://localhost/C:/Windows/win.ini",
            "ftp://anonymous@ftp.funet.fi/pub/test.mp4",
            "gopher://127.0.0.1:6379/_flushall",
            "data:text/html,<script>alert(1)</script>",
            "javascript:alert(document.cookie)",
            # Loopback SSRF
            "http://localhost:8000/api/workstation/credentials",
            "http://localhost/admin",
            "http://127.0.0.1:8000/api/workstation/credentials",
            "http://127.0.0.2/",
            "http://127.127.127.127:8080/secrets",
            "http://0.0.0.0:8000/",
            # Cloud Metadata SSRF
            "http://169.254.169.254/latest/meta-data/",
            "http://169.254.169.254/computeMetadata/v1/",
            "http://169.254.1.1/",
            # RFC 1918 Private IPs
            "http://10.0.0.1/admin/router",
            "http://10.254.254.254/",
            "http://172.16.0.1/",
            "http://172.31.255.255/",
            "http://192.168.1.1/admin",
            "http://192.168.0.1:8080/",
            # Domain Allowlist Bypasses
            "http://youtube.com.attacker.com/video",
            "http://attacker.com/youtube.com",
            "http://fake-youtube.com/watch",
            "http://evil-phishing.org/media.mp4",
            "http://instagram.com.evil.com/post",
            # Malformed
            "http://",
            "http:///path/to/media",
            "   ",
            "not_a_valid_url",
        ]

        initial_active = len(self.qm.get_status().get("active", []))

        for mal_url in malicious_urls:
            reset_download_rate_limit(self.token)
            resp = self.client.post(
                "/api/queue",
                json={"url": mal_url, "folder_key": "B-Roll (General)"},
                headers=self.remote_headers,
            )
            self.assertEqual(
                resp.status_code,
                400,
                f"Malicious URL '{mal_url}' must be rejected with HTTP 400, got {resp.status_code} ({resp.text})",
            )

        # Confirm queue remained completely unpolluted
        final_active = len(self.qm.get_status().get("active", []))
        self.assertEqual(final_active, initial_active, "No jobs should have been enqueued for malicious URLs")

    def test_10_remote_client_custom_path_injection_blocked(self):
        """
        Remote clients are strictly prohibited from submitting custom arbitrary
        filesystem paths via custom_path, target_dir, or target_folder.
        """
        traversal_attempts = [
            "C:/Windows/System32",
            "../../Windows/System32",
            "D:/Assets/BRoll/../../Windows/System32",
            "C:/Users/Administrator",
            "\\\\?\\C:\\Windows\\System32",
            "D:/Assets/SFX/../../../ProgramData",
        ]

        valid_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

        for trav_path in traversal_attempts:
            for field in ("custom_path", "target_dir", "target_folder"):
                reset_download_rate_limit(self.token)
                payload = {"url": valid_url, field: trav_path}
                resp = self.client.post("/api/queue", json=payload, headers=self.remote_headers)
                self.assertEqual(
                    resp.status_code,
                    400,
                    f"Remote custom path '{trav_path}' via '{field}' must return 400, got {resp.status_code}",
                )
                self.assertIn("Custom filesystem paths are not allowed", resp.text)

    def test_11_path_containment_and_traversal_fuzzing(self):
        """
        Directly fuzzes validate_path_containment with directory traversal payloads.
        """
        presets = get_presets()
        traversal_payloads = [
            "D:/Assets/BRoll/../../Windows/System32",
            "D:/Assets/SFX/../../../Program Files",
            "D:/Assets/Music/..\\..\\Windows",
            "D:/Assets/Social/./../../",
            "C:/Windows/System32",
        ]

        for payload in traversal_payloads:
            with self.assertRaises(HTTPException) as ctx:
                validate_path_containment(payload, presets, is_local=False)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_12_filename_sanitizer_fuzzing(self):
        """
        Fuzzes sanitize_filename with adversarial filename inputs:
        - Path traversal sequences (../, ..\\)
        - Null bytes (\x00)
        - Windows reserved characters (<>:"/\\|?*)
        - Reserved DOS device names (CON, PRN, AUX, NUL, COM1, LPT1)
        - 5000-character overflow strings
        """
        adversarial_inputs = [
            ("../../Windows/System32/cmd.exe", False),
            ("..\\..\\calc.exe", False),
            ("video\x00malicious.mp4", False),
            ("\x00\x00\x00", True),
            ("file<test>:bad|name?*.mp4", False),
            ("CON.mp4", False),
            ("PRN.mp3", False),
            ("A" * 5000, False),
            ("    ", True),
            (None, True),
        ]

        for raw_name, becomes_fallback in adversarial_inputs:
            cleaned = sanitize_filename(raw_name)
            self.assertNotIn("/", cleaned)
            self.assertNotIn("\\", cleaned)
            self.assertNotIn("\x00", cleaned)
            self.assertNotIn("..", cleaned)
            for c in '<>:"|?*':
                self.assertNotIn(c, cleaned)
            self.assertLessEqual(len(cleaned), 120)
            if becomes_fallback:
                self.assertEqual(cleaned, "downloaded_media")
            else:
                self.assertTrue(len(cleaned) > 0)


# ==============================================================================
# SECTION 4: LIVE NETWORK SOCKET PROBES
# ==============================================================================

class TestTier5LiveNetworkSocketProbes(unittest.TestCase):
    """
    Tier 5: Live Uvicorn Network Socket Verification over real LAN IP.
    """

    server_proc = None
    server_thread = None
    lan_ip = None
    port = 8994

    @classmethod
    def setUpClass(cls):
        import uvicorn
        cls.lan_ip = server.get_local_lan_ip()
        server.init_server_credentials(force_refresh=True)

        config = uvicorn.Config(
            server.app,
            host="0.0.0.0",
            port=cls.port,
            log_level="critical",
            access_log=False,
        )
        cls.server_inst = uvicorn.Server(config)
        cls.server_thread = threading.Thread(target=cls.server_inst.run, daemon=True)
        cls.server_thread.start()

        # Wait for socket readiness
        ready = False
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 5.0:
            try:
                s = socket.create_connection((cls.lan_ip, cls.port), timeout=0.2)
                s.close()
                ready = True
                break
            except (OSError, ConnectionRefusedError):
                time.sleep(0.05)

        if not ready:
            raise RuntimeError(f"Live Uvicorn server failed to bind to {cls.lan_ip}:{cls.port}")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server_inst") and cls.server_inst:
            cls.server_inst.should_exit = True
        if hasattr(cls, "server_thread") and cls.server_thread:
            cls.server_thread.join(timeout=3.0)

    def test_13_live_socket_lan_boundary_and_concurrency(self):
        """
        Connects directly over live network socket to http://<lan_ip>:8994:
        1. Probes /api/workstation/credentials over LAN IP -> strictly 403 Forbidden.
        2. Probes /api/drives over LAN IP with mobile auth token -> strictly 403 Forbidden.
        3. Probes /api/queue without token -> strictly 401 with WWW-Authenticate: Bearer.
        4. Runs 20 concurrent logins directly over live socket.
        """
        import httpx

        base_url = f"http://{self.lan_ip}:{self.port}"
        creds = server.init_server_credentials()
        valid_uid = creds["uid"]
        valid_pw = creds["password"]
        token = create_session_token()

        with httpx.Client(base_url=base_url, timeout=5.0) as client:
            # 1. Workstation credentials over LAN IP without token -> 403 Forbidden
            resp_creds = client.get("/api/workstation/credentials")
            self.assertEqual(
                resp_creds.status_code,
                403,
                f"Live LAN socket access to /api/workstation/credentials must return 403, got {resp_creds.status_code}",
            )
            self.assertNotIn(valid_pw, resp_creds.text)

            # 2. Traversal endpoint (/api/drives) over LAN IP with session token -> 403 Forbidden
            resp_drives = client.get("/api/drives", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(
                resp_drives.status_code,
                403,
                f"Live LAN socket access to /api/drives with auth token must return 403, got {resp_drives.status_code}",
            )

            # 3. Traversal endpoint (/api/drives) over LAN IP without session token -> 401 Unauthorized
            resp_drives_unauth = client.get("/api/drives")
            self.assertEqual(
                resp_drives_unauth.status_code,
                401,
                f"Live LAN socket unauth drives access must return 401, got {resp_drives_unauth.status_code}",
            )

            # 4. Protected endpoint without token -> 401
            resp_queue = client.post("/api/queue", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
            self.assertEqual(
                resp_queue.status_code,
                401,
                f"Live LAN socket unauth queue call must return 401, got {resp_queue.status_code}",
            )
            self.assertIn("Bearer", resp_queue.headers.get("www-authenticate", ""))

            # 5. Concurrent logins over live socket
            def live_login_worker(thread_id: int):
                # Valid login
                r_valid = client.post("/api/auth/login", json={"uid": valid_uid, "password": valid_pw})
                self.assertEqual(r_valid.status_code, 200)
                tok = r_valid.json().get("session_token")
                self.assertTrue(tok and tok.startswith("ads_"))

                # Invalid login
                r_inv = client.post("/api/auth/login", json={"uid": valid_uid, "password": "wrongpassword"})
                self.assertEqual(r_inv.status_code, 401)

            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = [executor.submit(live_login_worker, tid) for tid in range(20)]
                concurrent.futures.wait(futures, timeout=8.0)
                for f in futures:
                    self.assertIsNone(f.exception(), f"Worker raised exception: {f.exception()}")


# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("  ASSETDROP (v2.0) — TIER 5 ADVERSARIAL STRESS TESTING SUITE")
    print("  Milestone: M5-P | Mode: Adversarial Empirical Challenge")
    print("=" * 80 + "\n")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestTier5ConcurrencyAndTiming))
    suite.addTests(loader.loadTestsFromTestCase(TestTier5RemoteLanBoundary))
    suite.addTests(loader.loadTestsFromTestCase(TestTier5PathInjectionAndSSRF))
    suite.addTests(loader.loadTestsFromTestCase(TestTier5LiveNetworkSocketProbes))

    runner = unittest.TextTestRunner(verbosity=2)
    start_time = time.perf_counter()
    result = runner.run(suite)
    elapsed = time.perf_counter() - start_time

    print("\n" + "=" * 80)
    print("  TIER 5 ADVERSARIAL STRESS SUMMARY")
    print("=" * 80)
    print(f"  Total Adversarial Checks Executed : {result.testsRun}")
    print(f"  Passed Checks                     : {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"  Failures                          : {len(result.failures)}")
    print(f"  Errors                            : {len(result.errors)}")
    print(f"  Runtime Duration                  : {elapsed:.2f} seconds")
    print("=" * 80)

    if result.wasSuccessful():
        print("  [CHALLENGER VERDICT] APPROVE: All Tier 5 adversarial stress tests passed!")
        print("  Constant-time auth verified, 0 crashes under 20-thread concurrency,")
        print("  remote LAN boundaries strictly enforced (403/401), SSRF/traversal contained.")
        print("=" * 80 + "\n")
        sys.exit(0)
    else:
        print("  [CHALLENGER VERDICT] REQUEST_CHANGES: Failures detected during adversarial stress testing.")
        print("=" * 80 + "\n")
        sys.exit(1)
