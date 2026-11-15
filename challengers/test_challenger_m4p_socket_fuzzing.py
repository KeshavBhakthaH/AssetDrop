"""
challengers/test_challenger_m4p_socket_fuzzing.py — Adversarial Network Socket Fuzzing Suite.

Milestone: M4-P Final Gate Review
Agent: challenger_m4p_6 (teamwork_challenger)

Probes:
1. POST /api/auth/login over network socket with non-ASCII unicode, emojis, SQLi, null-bytes,
   empty payloads, malformed JSON, and type confusion.
2. GET /api/shared-folders?token=... over remote network socket with adversarial tokens.
3. GET /api/workstation/credentials over remote network socket (strictly 403 Forbidden).
4. Raw TCP socket fuzzing: sending raw HTTP byte streams directly over TCP sockets.
5. Verifies:
   - Zero crashes (0 HTTP 500 Internal Server Errors).
   - Zero socket disconnects / unhandled exceptions.
   - Clean 401 Unauthorized / 403 Forbidden rejections.
   - Zero data leakage (passwords, tokens, absolute Windows paths).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import sys
import threading
import time
import unittest
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import httpx
import uvicorn
import server
from core.auth import create_session_token, verify_session_token, revoke_session_token


class NetworkSocketFuzzer:
    """Helper to start an ephemeral Uvicorn server and perform socket-level fuzzing."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8991):
        self.host = host
        self.port = port
        self.lan_ip = server.get_local_lan_ip()
        self.server_inst: Optional[uvicorn.Server] = None
        self.thread: Optional[threading.Thread] = None
        self.creds: Dict[str, Any] = {}

    def start(self):
        # Mute logging during fuzzing
        logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
        logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)
        logging.getLogger("assetdrop").setLevel(logging.ERROR)

        server.init_server_credentials(force_refresh=True)
        self.creds = server.init_server_credentials()

        config = uvicorn.Config(
            server.app,
            host=self.host,
            port=self.port,
            log_level="critical",
            access_log=False,
        )
        self.server_inst = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server_inst.run, daemon=True)
        self.thread.start()

        # Wait for server readiness
        start_wait = time.perf_counter()
        ready = False
        while time.perf_counter() - start_wait < 5.0:
            try:
                s = socket.create_connection((self.lan_ip, self.port), timeout=0.2)
                s.close()
                ready = True
                break
            except (OSError, ConnectionRefusedError):
                time.sleep(0.05)

        if not ready:
            raise RuntimeError(f"Uvicorn server failed to bind to {self.lan_ip}:{self.port}")

    def stop(self):
        if self.server_inst:
            self.server_inst.should_exit = True
        if self.thread:
            self.thread.join(timeout=3.0)

    def raw_tcp_request(self, raw_bytes: bytes) -> Tuple[int, Dict[str, str], bytes]:
        """Sends raw bytes over a TCP socket and parses HTTP status code and response."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.connect((self.lan_ip, self.port))
        s.sendall(raw_bytes)

        response_chunks = []
        while True:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    break
                response_chunks.append(chunk)
                if b"\r\n\r\n" in b"".join(response_chunks):
                    # Check if body is finished if content-length given
                    all_data = b"".join(response_chunks)
                    header_part, _, body_part = all_data.partition(b"\r\n\r\n")
                    # simple check for content-length
                    cl_idx = header_part.lower().find(b"content-length:")
                    if cl_idx != -1:
                        cl_val = int(header_part[cl_idx:].split(b"\r\n")[0].split(b":")[1].strip())
                        if len(body_part) >= cl_val:
                            break
                    else:
                        break
            except socket.timeout:
                break
        s.close()

        raw_resp = b"".join(response_chunks)
        if not raw_resp:
            return 0, {}, b""

        parts = raw_resp.split(b"\r\n\r\n", 1)
        header_text = parts[0].decode("utf-8", errors="replace")
        body = parts[1] if len(parts) > 1 else b""

        lines = header_text.split("\r\n")
        status_line = lines[0]
        status_code = int(status_line.split()[1]) if len(status_line.split()) > 1 else 0

        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        return status_code, headers, body


class TestAdversarialSocketFuzzing(unittest.TestCase):
    """Adversarial security fuzzing suite over live network socket."""

    fuzzer: NetworkSocketFuzzer

    @classmethod
    def setUpClass(cls):
        # Choose a free port
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("", 0))
        port = s.getsockname()[1]
        s.close()

        cls.fuzzer = NetworkSocketFuzzer(port=port)
        cls.fuzzer.start()
        cls.base_url = f"http://{cls.fuzzer.lan_ip}:{cls.fuzzer.port}"
        cls.valid_uid = cls.fuzzer.creds["uid"]
        cls.valid_password = cls.fuzzer.creds["password"]
        cls.http_client = httpx.Client(base_url=cls.base_url, timeout=5.0)

    @classmethod
    def tearDownClass(cls):
        cls.http_client.close()
        cls.fuzzer.stop()

    # =========================================================================
    # 1. POST /api/auth/login Adversarial Socket Fuzzing
    # =========================================================================
    def test_01_login_non_ascii_unicode_fuzzing(self):
        """Probes /api/auth/login with diverse non-ASCII unicode strings in UID & password."""
        unicode_vectors = [
            ("ogham_script", "᚛᚛ᚑᚌᚐᚋ᚜᚜"),
            ("arabic_script", "مرحبا بالعالم"),
            ("cjk_ideographs", "你好世界漢字"),
            ("cyrillic_script", "Привет мир"),
            ("hebrew_script", "שלום עולם"),
            ("devanagari_hindi", "नमस्ते दुनिया"),
            ("combining_diacritics_zalgo", "Z͑ͫ̓ͪ̂ͫ̽͏̴̙̤̞͉͚̯̞A̧̭̥͔̙ͫͪͥ̀ͭ̌͜͝L̠ͨͧͩ͘G̛͖̜̑ͣ̌ͬ́͂O̘̘ͪͨ͊̀̚͜͢"),
            ("math_symbols", "∀x∈ℝ: x²≥0 ∧ ∑_{i=1}^n i = n(n+1)/2"),
            ("accented_latin", "Crème brûlée naïve façade résumé"),
        ]

        for label, uvec in unicode_vectors:
            # Case A: Unicode password with valid UID
            resp = self.http_client.post("/api/auth/login", json={"uid": self.valid_uid, "password": uvec})
            self.assertEqual(resp.status_code, 401, f"Unicode pw [{label}] returned {resp.status_code} instead of 401")
            self.assertFalse(resp.json().get("success", False))
            self.assertNotIn("session_token", resp.json())

            # Case B: Unicode UID with valid password
            resp2 = self.http_client.post("/api/auth/login", json={"uid": uvec, "password": self.valid_password})
            self.assertEqual(resp2.status_code, 401, f"Unicode uid [{label}] returned {resp2.status_code} instead of 401")
            self.assertFalse(resp2.json().get("success", False))

            # Case C: Unicode in both
            resp3 = self.http_client.post("/api/auth/login", json={"uid": uvec, "password": uvec})
            self.assertEqual(resp3.status_code, 401, f"Unicode both [{label}] returned {resp3.status_code} instead of 401")

    def test_02_login_emoji_fuzzing(self):
        """Probes /api/auth/login with emojis, surrogate pairs, and composite glyphs."""
        emoji_vectors = [
            ("fire_rocket", "🔥🚀"),
            ("bomb_skull", "💣💀💥"),
            ("compound_family", "👨‍👩‍👧‍👦"),
            ("flag_zwj", "🏳️‍🌈"),
            ("key_lock", "🔑🔐🔓"),
            ("extended_pictographic", "🪐✨🦖🦕🛸"),
            ("mixed_emojis_ascii", f"pass_{self.valid_password}_🔥"),
        ]

        for label, evec in emoji_vectors:
            resp = self.http_client.post("/api/auth/login", json={"uid": self.valid_uid, "password": evec})
            self.assertEqual(resp.status_code, 401, f"Emoji pw [{label}] returned {resp.status_code} instead of 401")
            self.assertFalse(resp.json().get("success", False))
            self.assertNotIn("session_token", resp.json())

            resp2 = self.http_client.post("/api/auth/login", json={"uid": evec, "password": self.valid_password})
            self.assertEqual(resp2.status_code, 401, f"Emoji uid [{label}] returned {resp2.status_code} instead of 401")

    def test_03_login_sqli_injection_fuzzing(self):
        """Probes /api/auth/login with SQL injection payloads."""
        sqli_vectors = [
            ("tautology_single_quote", "' OR '1'='1"),
            ("tautology_double_quote", '" OR "1"="1'),
            ("tautology_comment", "admin'--"),
            ("union_select", "' UNION SELECT null, null, null--"),
            ("stacked_queries", "'; DROP TABLE users; --"),
            ("boolean_blind", "' AND 1=(SELECT COUNT(*) FROM tabname); --"),
            ("numeric_bypass", "10000 OR 1=1"),
            ("nosql_syntax", '{"$gt": ""}'),
        ]

        for label, svec in sqli_vectors:
            resp = self.http_client.post("/api/auth/login", json={"uid": self.valid_uid, "password": svec})
            self.assertEqual(resp.status_code, 401, f"SQLi pw [{label}] returned {resp.status_code} instead of 401")
            self.assertFalse(resp.json().get("success", False))
            self.assertNotIn("session_token", resp.json())

            resp2 = self.http_client.post("/api/auth/login", json={"uid": svec, "password": self.valid_password})
            self.assertEqual(resp2.status_code, 401, f"SQLi uid [{label}] returned {resp2.status_code} instead of 401")

    def test_04_login_null_byte_and_control_chars_fuzzing(self):
        """Probes /api/auth/login with null bytes and control characters."""
        null_vectors = [
            ("literal_null_middle", f"{self.valid_password}\x00extra"),
            ("literal_null_start", f"\x00{self.valid_password}"),
            ("literal_null_only", "\x00"),
            ("escaped_null", "\\0"),
            ("json_escaped_null", "\\u0000"),
            ("bell_backspace", "\x07\x08\x1b"),
        ]

        for label, nvec in null_vectors:
            resp = self.http_client.post("/api/auth/login", json={"uid": self.valid_uid, "password": nvec})
            self.assertEqual(resp.status_code, 401, f"Null pw [{label}] returned {resp.status_code} instead of 401")
            self.assertFalse(resp.json().get("success", False))

            resp2 = self.http_client.post("/api/auth/login", json={"uid": nvec, "password": self.valid_password})
            self.assertEqual(resp2.status_code, 401, f"Null uid [{label}] returned {resp2.status_code} instead of 401")

    def test_05_login_empty_and_malformed_payloads(self):
        """Probes /api/auth/login with empty bodies, whitespace, and schema violations."""
        # Empty JSON
        resp = self.http_client.post("/api/auth/login", json={})
        self.assertIn(resp.status_code, (400, 422), f"Empty JSON returned unexpected status {resp.status_code}")

        # Empty strings
        resp = self.http_client.post("/api/auth/login", json={"uid": "", "password": ""})
        self.assertEqual(resp.status_code, 401)

        # Whitespace strings
        resp = self.http_client.post("/api/auth/login", json={"uid": "     ", "password": "   \t\n  "})
        self.assertEqual(resp.status_code, 401)

        # Null values in fields
        resp = self.http_client.post("/api/auth/login", json={"uid": None, "password": None})
        self.assertIn(resp.status_code, (400, 422))

        # Array instead of object
        resp = self.http_client.post("/api/auth/login", json=["uid", "password"])
        self.assertIn(resp.status_code, (400, 422))

        # 5000 character overflow strings
        huge_str = "X" * 5000
        resp = self.http_client.post("/api/auth/login", json={"uid": huge_str, "password": huge_str})
        self.assertEqual(resp.status_code, 401)

    # =========================================================================
    # 2. GET /api/shared-folders Remote Network Socket Fuzzing
    # =========================================================================
    def test_06_shared_folders_remote_token_fuzzing(self):
        """
        Probes GET /api/shared-folders?token=... from remote socket with adversarial vectors.
        Must strictly return 401 Unauthorized with header 'WWW-Authenticate: Bearer'.
        Zero data leakage (no folder lists, no absolute filesystem paths).
        """
        bad_tokens = [
            ("empty_token", ""),
            ("whitespace_token", "   \t "),
            ("non_ascii_ogham", "᚛᚛ᚑᚌᚐᚋ᚜᚜"),
            ("emojis_fire_rocket", "🔥🚀💣"),
            ("sqli_token", "' OR '1'='1"),
            ("null_byte_token", "ads_\x00test"),
            ("unprefixed_random_hex", secrets.token_hex(16)),
            ("forged_ads_prefix_token", f"ads_{secrets.token_hex(16)}"),
            ("extremely_long_token", "ads_" + "A" * 2000),
        ]

        # First verify endpoint without token returns 401
        resp_notoken = self.http_client.get("/api/shared-folders")
        self.assertEqual(resp_notoken.status_code, 401, "GET /api/shared-folders without token should return 401")
        self.assertEqual(resp_notoken.headers.get("www-authenticate"), "Bearer")

        for label, bad_tok in bad_tokens:
            # Query parameter vector ?token=...
            resp = self.http_client.get(f"/api/shared-folders?token={quote(bad_tok)}")
            self.assertEqual(
                resp.status_code,
                401,
                f"Query token [{label}] returned {resp.status_code} instead of 401",
            )
            self.assertEqual(resp.headers.get("www-authenticate"), "Bearer")
            self.assertNotIn("folders", resp.json())
            self.assertNotIn("C:\\", resp.text)
            self.assertNotIn("D:\\", resp.text)

            # Header vector Authorization: Bearer <bad_tok> (for tokens that are valid ascii header values)
            if bad_tok.isascii() and "\x00" not in bad_tok and bad_tok.strip():
                resp2 = self.http_client.get("/api/shared-folders", headers={"Authorization": f"Bearer {bad_tok}"})
                self.assertEqual(
                    resp2.status_code,
                    401,
                    f"Header Bearer [{label}] returned {resp2.status_code} instead of 401",
                )
                self.assertEqual(resp2.headers.get("www-authenticate"), "Bearer")

    def test_07_revoked_token_immediate_rejection(self):
        """Verifies that a valid session token, once revoked, is immediately rejected with 401."""
        # 1. Login with valid credentials to get real session token
        login_resp = self.http_client.post(
            "/api/auth/login",
            json={"uid": self.valid_uid, "password": self.valid_password},
        )
        self.assertEqual(login_resp.status_code, 200)
        token = login_resp.json()["session_token"]
        self.assertTrue(token.startswith("ads_"))

        # 2. Access /api/shared-folders with valid token -> 200 OK
        resp = self.http_client.get(f"/api/shared-folders?token={token}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("folders", body)
        for folder in body["folders"]:
            self.assertIn("id", folder)
            self.assertIn("name", folder)
            # Crucial security assertion: remote client MUST NEVER see disk path
            self.assertNotIn("path", folder)

        # 3. Revoke token via logout
        logout_resp = self.http_client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(logout_resp.status_code, 200)

        # 4. Immediate re-probe with revoked token must fail with 401
        post_logout_resp = self.http_client.get(f"/api/shared-folders?token={token}")
        self.assertEqual(
            post_logout_resp.status_code,
            401,
            "Revoked token was unexpectedly accepted on /api/shared-folders!",
        )
        self.assertEqual(post_logout_resp.headers.get("www-authenticate"), "Bearer")

    # =========================================================================
    # 3. Workstation Endpoints Remote Access Protection (403 Forbidden)
    # =========================================================================
    def test_08_workstation_endpoints_remote_socket_forbidden(self):
        """
        Verifies that workstation endpoints return 403 Forbidden when accessed
        over the remote LAN socket, even with a valid mobile auth token.
        """
        # Create a valid mobile token
        valid_token = create_session_token()
        self.assertTrue(verify_session_token(valid_token))

        workstation_endpoints = [
            "/api/workstation/credentials",
            "/api/workstation/settings",
            "/api/workstation/info",
        ]

        for ep in workstation_endpoints:
            # Without token
            resp = self.http_client.get(ep)
            self.assertEqual(
                resp.status_code,
                403,
                f"Workstation endpoint {ep} without token returned {resp.status_code} (expected 403)",
            )
            self.assertNotIn(self.valid_password, resp.text)

            # With valid mobile session token (still forbidden to remote clients)
            resp2 = self.http_client.get(ep, headers={"Authorization": f"Bearer {valid_token}"})
            self.assertEqual(
                resp2.status_code,
                403,
                f"Workstation endpoint {ep} with valid mobile token returned {resp2.status_code} (expected 403)",
            )
            self.assertNotIn(self.valid_password, resp2.text)

        revoke_session_token(valid_token)

    # =========================================================================
    # 4. Raw TCP Low-Level Socket Fuzzing (Raw Bytes over Wire)
    # =========================================================================
    def test_09_raw_tcp_socket_fuzzing(self):
        """
        Sends raw crafted TCP byte packets directly to testserver port.
        Verifies zero server crashes (no 500, no connection drops without response).
        """
        # Vector 1: Raw JSON with emojis and non-ASCII over HTTP/1.1 POST
        payload1 = json.dumps({"uid": "᚛᚛ᚑᚌᚐᚋ᚜᚜", "password": "🔥🚀💥\x00extra"}).encode("utf-8")
        req1 = (
            b"POST /api/auth/login HTTP/1.1\r\n"
            b"Host: testserver\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            b"Content-Length: " + str(len(payload1)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n\r\n" + payload1
        )
        status, headers, body = self.fuzzer.raw_tcp_request(req1)
        self.assertEqual(status, 401, f"Raw TCP unicode/emoji probe returned {status}")
        self.assertNotIn(b"500 Internal Server Error", body)

        # Vector 2: Raw malformed HTTP garbage request (syntactically invalid JSON)
        payload2 = b"{bad_json"
        req2 = (
            b"POST /api/auth/login HTTP/1.1\r\n"
            b"Host: testserver\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(payload2)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n\r\n" + payload2
        )
        status2, headers2, body2 = self.fuzzer.raw_tcp_request(req2)
        self.assertIn(status2, (400, 422), f"Raw TCP bad json returned unexpected {status2}")
        self.assertNotIn(b"500 Internal Server Error", body2)

        # Vector 3: Raw probe on /api/shared-folders with null byte in query string
        req3 = (
            b"GET /api/shared-folders?token=ads_token%00extra HTTP/1.1\r\n"
            b"Host: testserver\r\n"
            b"Connection: close\r\n\r\n"
        )
        status3, headers3, body3 = self.fuzzer.raw_tcp_request(req3)
        self.assertEqual(status3, 401, f"Raw TCP null query returned unexpected {status3}")
        self.assertNotIn(b"500 Internal Server Error", body3)

        # Vector 4: Raw header injection with CRLF attack attempt
        req4 = (
            b"GET /api/shared-folders HTTP/1.1\r\n"
            b"Host: testserver\r\n"
            b"Authorization: Bearer ads_token\r\nX-Injected-Header: admin\r\n"
            b"Connection: close\r\n\r\n"
        )
        status4, headers4, body4 = self.fuzzer.raw_tcp_request(req4)
        self.assertIn(status4, (400, 401), f"Raw TCP header injection returned unexpected {status4}")
        self.assertNotIn(b"500 Internal Server Error", body4)


def run_socket_fuzzing_suite() -> int:
    print("=" * 80)
    print("  ASSETDROP (v2.0) — ADVERSARIAL NETWORK SOCKET FUZZING SUITE")
    print("  Target: Live Uvicorn Network Socket | Host: 0.0.0.0 (LAN IP Probe)")
    print("=" * 80)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestAdversarialSocketFuzzing)
    runner = unittest.TextTestRunner(verbosity=2)

    start_time = time.perf_counter()
    result = runner.run(suite)
    duration = time.perf_counter() - start_time

    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passed = total - failures - errors

    print("=" * 80)
    print("  SOCKET FUZZING SUMMARY")
    print("=" * 80)
    print(f"  Total Probes Executed : {total}")
    print(f"  Passed Checks         : {passed}")
    print(f"  Failures              : {failures}")
    print(f"  Errors                : {errors}")
    print(f"  Runtime Duration      : {duration:.2f} seconds")
    print("=" * 80)

    if failures == 0 and errors == 0:
        print("  [VERDICT] APPROVE: All network socket fuzzing probes passed.")
        print("  Zero 500 crashes, strict 401/403 enforcement, zero data leakage.")
        print("=" * 80)
        return 0
    else:
        print("  [VERDICT] REQUEST_CHANGES: Socket fuzzing failure or crash detected.")
        print("=" * 80)
        return 1


if __name__ == "__main__":
    sys.exit(run_socket_fuzzing_suite())
