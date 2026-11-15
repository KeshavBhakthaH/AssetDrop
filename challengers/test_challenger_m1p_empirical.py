"""
tests/test_challenger_m1p_empirical.py

Milestone M1-P Empirical Stress & Boundary Challenge Suite:
1. Property-Based Testing of `derive_server_uid(ip)` over 1,000+ random and adversarial IPs:
   - Format: exactly 5 characters
   - Numeric digits only: isdigit() is True
   - Value range: 10000 <= int(uid) <= 99999
   - No leading zero: uid[0] != '0'
   - Determinism: derive_server_uid(ip) == derive_server_uid(ip)
   - Adversarial inputs: IPv4, IPv6, localhost variants, empty, whitespace, unicode, 10KB strings, injection payloads.
2. Password Entropy & Uniqueness over 500 samples:
   - Length: exactly 8 characters
   - Hexadecimal characters only
   - Zero collisions across 500 samples
   - Entropy & distribution sanity check
3. Thread-Safe Concurrency Stress on `core.auth`:
   - 20 concurrent threads running simultaneous token creation, verification, revocation, and count checks
   - Race-condition testing under high contention
   - Zero deadlock, zero unhandled concurrency exceptions
4. Login Endpoint Fuzzing & Boundary Inputs:
   - POST /api/auth/login with null, integer, float, boolean, list, object, empty, and 1MB payloads
   - Malformed JSON and raw byte streams (verifying 400/422 responses, never 500)
   - Invalid credentials boundary testing (clean 401s)
   - Full authentication round-trip with protected endpoints and logout revocation
"""

import collections
import concurrent.futures
import ipaddress
import json
import math
import random
import secrets
import os
import string
import sys
import threading
import time
import unittest
from typing import List, Set

# Ensure repository root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from starlette.testclient import TestClient

from core.auth import (
    clear_all_sessions,
    create_session_token,
    get_active_session_count,
    revoke_session_token,
    verify_session_token,
)
from core.config import derive_server_uid, generate_connection_password
import server



class TestM1PEmpiricalChallenge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure fresh server credentials
        server.init_server_credentials(force_refresh=True)
        cls.client = TestClient(server.app)
        cls.remote_client = TestClient(server.app, client=("192.168.1.188", 45678))

    def setUp(self):
        clear_all_sessions()

    def tearDown(self):
        clear_all_sessions()

    # =========================================================================
    # 1. PROPERTY-BASED UID DERIVATION TESTING (1,000+ SAMPLES)
    # =========================================================================
    def test_01_property_based_uid_derivation(self):
        """Stress-test derive_server_uid over 1,200+ varied and adversarial IP inputs."""
        test_inputs: List[str] = []

        # 1. 800 random IPv4 addresses
        for _ in range(800):
            rand_int = random.randint(0, 0xFFFFFFFF)
            test_inputs.append(str(ipaddress.IPv4Address(rand_int)))

        # 2. 500 random IPv6 addresses
        for _ in range(500):
            rand_int = random.randint(0, 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF)
            test_inputs.append(str(ipaddress.IPv6Address(rand_int)))

        # 3. Known special IPv4 / IPv6 addresses
        specials = [
            "0.0.0.0", "127.0.0.1", "127.0.1.1", "255.255.255.255",
            "10.0.0.1", "172.16.0.1", "192.168.0.1", "192.168.1.254",
            "::", "::1", "fe80::1", "2001:db8::1", "ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
            "localhost", "[::1]", "0.0.0.0:8000", "http://127.0.0.1:8000"
        ]
        test_inputs.extend(specials)

        # 4. Whitespace, empty, and unusual string variants
        whitespaces = [
            "", " ", "   ", "\t", "\n", "\r\n", "  192.168.1.1  ",
            "\t10.0.0.1\n", " 127.0.0.1 ", "   ::1   "
        ]
        test_inputs.extend(whitespaces)

        # 5. Internationalized / Unicode / Adversarial strings (200 samples)
        unicode_samples = [
            "１９２.１６８.１.１",  # Full-width
            "тест.192.168.1.1",     # Cyrillic
            "🚀.server.lan",        # Emoji
            "192.168.1.1; DROP TABLE users;--",
            "<script>alert('uid')</script>",
            "192.168.1.1\x00extra",
            "A" * 1000,             # 1 KB string
            "B" * 10000,            # 10 KB string
            "null", "None", "undefined", "true", "false", "0", "-1"
        ]
        test_inputs.extend(unicode_samples)

        # 6. Additional 200 random mixed strings
        for _ in range(200):
            length = random.randint(1, 64)
            test_inputs.append("".join(random.choices(string.printable, k=length)))

        total_tested = len(test_inputs)
        self.assertGreaterEqual(total_tested, 1200, f"Expected >= 1200 tests, got {total_tested}")

        uids_generated = set()
        min_uid = 999999
        max_uid = 0

        for idx, ip_input in enumerate(test_inputs):
            uid = derive_server_uid(ip_input)

            # Property 1: String type
            self.assertIsInstance(uid, str, f"Input {ip_input!r} produced non-string: {type(uid)}")

            # Property 2: Strictly 5 characters
            self.assertEqual(len(uid), 5, f"Input {ip_input!r} produced length {len(uid)} (expected 5): {uid!r}")

            # Property 3: Strictly digits
            self.assertTrue(uid.isdigit(), f"Input {ip_input!r} produced non-digit UID: {uid!r}")

            # Property 4: Integer range bounds [10000, 99999]
            val = int(uid)
            self.assertGreaterEqual(val, 10000, f"Input {ip_input!r} produced UID < 10000: {val}")
            self.assertLessEqual(val, 99999, f"Input {ip_input!r} produced UID > 99999: {val}")

            # Property 5: No leading zero
            self.assertNotEqual(uid[0], "0", f"Input {ip_input!r} produced UID with leading zero: {uid}")

            # Property 6: Determinism (idempotency)
            uid_second = derive_server_uid(ip_input)
            self.assertEqual(uid, uid_second, f"UID non-deterministic for input {ip_input!r}: {uid} != {uid_second}")

            uids_generated.add(uid)
            min_uid = min(min_uid, val)
            max_uid = max(max_uid, val)

        # Distribution / Spread sanity check
        # Across 1200+ distinct inputs, we expect high diversity (no collapsing to a single constant)
        unique_ratio = len(uids_generated) / total_tested
        self.assertGreater(unique_ratio, 0.90, f"Unique UID ratio too low: {unique_ratio:.2%} ({len(uids_generated)}/{total_tested})")
        self.assertLessEqual(min_uid, 20000, f"Minimum UID observed was unexpectedly high: {min_uid}")
        self.assertGreaterEqual(max_uid, 89000, f"Maximum UID observed was unexpectedly low: {max_uid}")

        print(f"\n[SUITE 1 PASS] Property-based UID tests passed: {total_tested} inputs tested, {len(uids_generated)} unique UIDs, range: [{min_uid}, {max_uid}].")

    # =========================================================================
    # 2. PASSWORD ENTROPY & UNIQUENESS (500 SAMPLES)
    # =========================================================================
    def test_02_password_entropy_and_uniqueness(self):
        """Stress-test generate_connection_password over 500 samples for uniqueness & entropy."""
        samples_count = 500
        passwords = [generate_connection_password() for _ in range(samples_count)]

        # Property 1: Exactly 500 samples
        self.assertEqual(len(passwords), samples_count)

        # Property 2: Zero collisions across 500 samples
        unique_passwords = set(passwords)
        self.assertEqual(len(unique_passwords), samples_count, f"Found collision in 500 passwords! Unique: {len(unique_passwords)}")

        # Property 3: All passwords have length 8 and are valid hex
        char_counts = collections.Counter()
        hex_chars = set("0123456789abcdef")

        for pw in passwords:
            self.assertIsInstance(pw, str)
            self.assertEqual(len(pw), 8, f"Password {pw!r} length is not 8")
            self.assertTrue(all(c in hex_chars for c in pw), f"Password {pw!r} contains non-hex characters")
            char_counts.update(pw)

        # Property 4: Character distribution check across 4,000 hex characters
        # With 16 hex characters uniform, expected frequency is 4000/16 = 250 per character
        total_chars = samples_count * 8
        expected_freq = total_chars / 16
        for ch in "0123456789abcdef":
            count = char_counts[ch]
            # 3-sigma tolerance: sqrt(250 * 15/16) ~ 15.3 -> 3 * 15.3 ~ 46. Let's allow generous [160, 340]
            self.assertGreater(count, 150, f"Char '{ch}' appears suspiciously infrequently: {count}")
            self.assertLess(count, 350, f"Char '{ch}' appears suspiciously frequently: {count}")

        # Compute empirical Shannon entropy
        entropy = 0.0
        for count in char_counts.values():
            p = count / total_chars
            entropy -= p * math.log2(p)
        # Theoretical max for 16 symbols is log2(16) = 4.0 bits/char
        self.assertGreater(entropy, 3.95, f"Empirical character entropy too low: {entropy:.4f} bits/char (expected ~4.0)")

        print(f"\n[SUITE 2 PASS] Password entropy test passed: {samples_count} samples, 0 collisions, Shannon entropy {entropy:.4f} bits/char (theoretical 4.0).")

    # =========================================================================
    # 3. SESSION CONCURRENCY & THREAD-SAFETY STRESS (20 THREADS)
    # =========================================================================
    def test_03_session_concurrency_stress(self):
        """Stress-test core.auth session store with 20 concurrent worker threads under high contention."""
        num_threads = 20
        ops_per_thread = 100
        barrier = threading.Barrier(num_threads)
        errors: List[str] = []
        created_tokens_all: List[str] = []
        tokens_lock = threading.Lock()

        def worker(thread_id: int):
            try:
                barrier.wait()  # Synchronize start to maximize contention
                local_tokens = []

                for i in range(ops_per_thread):
                    op_type = i % 4

                    if op_type == 0:
                        # Create token
                        token = create_session_token()
                        if not token.startswith("ads_") or len(token) != 36:
                            errors.append(f"Thread {thread_id}: Invalid token format: {token}")
                        local_tokens.append(token)
                        with tokens_lock:
                            created_tokens_all.append(token)

                    elif op_type == 1:
                        # Verify newly created local token
                        if local_tokens:
                            target = local_tokens[-1]
                            if not verify_session_token(target):
                                errors.append(f"Thread {thread_id}: Failed to verify active token {target}")
                            if not verify_session_token(f"Bearer {target}"):
                                errors.append(f"Thread {thread_id}: Failed to verify Bearer prefixed token {target}")

                    elif op_type == 2:
                        # Negative verification (invalid / random tokens)
                        bogus = f"ads_{secrets.token_hex(16)}"
                        if verify_session_token(bogus):
                            errors.append(f"Thread {thread_id}: Bogus token unexpectedly verified: {bogus}")
                        if verify_session_token(None):
                            errors.append(f"Thread {thread_id}: None token unexpectedly verified")

                    elif op_type == 3:
                        # Revoke an old local token
                        if local_tokens:
                            to_revoke = local_tokens.pop(0)
                            if not revoke_session_token(to_revoke):
                                errors.append(f"Thread {thread_id}: Failed to revoke token {to_revoke}")
                            if verify_session_token(to_revoke):
                                errors.append(f"Thread {thread_id}: Revoked token still verified: {to_revoke}")

                    # Periodic count check
                    _ = get_active_session_count()

            except Exception as exc:
                errors.append(f"Thread {thread_id} crashed with exception: {exc}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        start_time = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.perf_counter() - start_time

        self.assertEqual(len(errors), 0, f"Encountered concurrency errors: {errors[:5]}")
        active_count = get_active_session_count()
        self.assertGreaterEqual(active_count, 0)
        self.assertLessEqual(active_count, num_threads * ops_per_thread)

        # Final cleanup test under concurrency: clear_all_sessions
        clear_all_sessions()
        self.assertEqual(get_active_session_count(), 0)

        total_ops = num_threads * ops_per_thread
        print(f"\n[SUITE 3 PASS] Concurrency stress test passed: {num_threads} threads, {total_ops} operations in {elapsed:.3f}s ({total_ops/elapsed:.1f} ops/sec). 0 errors.")

    # =========================================================================
    # 4. LOGIN ENDPOINT FUZZING & BOUNDARY INPUTS
    # =========================================================================
    def test_04_login_endpoint_fuzzing_and_boundaries(self):
        """Fuzz POST /api/auth/login with malformed payloads, oversized data, and boundary cases."""
        creds_res = self.client.get("/api/workstation/credentials")
        self.assertEqual(creds_res.status_code, 200)
        creds = creds_res.json()
        valid_uid = creds["uid"]
        valid_pw = creds["password"]

        # 1. Missing fields (FastAPI validation -> 422)
        missing_payloads = [
            {},
            {"uid": valid_uid},
            {"password": valid_pw},
            {"other_key": "some_value"},
        ]
        for p in missing_payloads:
            res = self.remote_client.post("/api/auth/login", json=p)
            self.assertEqual(res.status_code, 422, f"Payload {p} should return 422, got {res.status_code}")

        # 2. Type violations / schema fuzzing (FastAPI validation -> 422)
        type_violation_payloads = [
            {"uid": None, "password": valid_pw},
            {"uid": valid_uid, "password": None},
            {"uid": [valid_uid], "password": valid_pw},
            {"uid": valid_uid, "password": {"secret": valid_pw}},
            {"uid": 12345, "password": valid_pw},  # FastAPI may coerce or reject; verify NOT 500
            {"uid": True, "password": valid_pw},
        ]
        for p in type_violation_payloads:
            res = self.remote_client.post("/api/auth/login", json=p)
            # Acceptable status codes are 422 (Unprocessable Entity) or 401 (if coerced but wrong). Never 500!
            self.assertIn(res.status_code, (401, 422), f"Type fuzz payload {p} returned unexpected status {res.status_code}")

        # 3. Empty strings and whitespace payloads (Should return 401 Unauthorized, never 500)
        empty_payloads = [
            {"uid": "", "password": ""},
            {"uid": "   ", "password": "   "},
            {"uid": "\t\n", "password": "\t\n"},
            {"uid": "", "password": valid_pw},
            {"uid": valid_uid, "password": ""},
        ]
        for p in empty_payloads:
            res = self.remote_client.post("/api/auth/login", json=p)
            self.assertEqual(res.status_code, 401, f"Empty payload {p} should return 401, got {res.status_code}")

        # 4. Wrong credentials boundary testing (401 Unauthorized)
        invalid_creds = [
            {"uid": "00000", "password": valid_pw},
            {"uid": "99999" if valid_uid != "99999" else "11111", "password": valid_pw},
            {"uid": valid_uid, "password": "wrongpassword"},
            {"uid": valid_uid, "password": valid_pw.upper() if valid_pw != valid_pw.upper() else "00000000"},
            {"uid": "1234", "password": valid_pw},      # 4 digits
            {"uid": "123456", "password": valid_pw},    # 6 digits
            {"uid": "-1000", "password": valid_pw},
            {"uid": "ABCDE", "password": valid_pw},
        ]
        for p in invalid_creds:
            res = self.remote_client.post("/api/auth/login", json=p)
            self.assertEqual(res.status_code, 401, f"Invalid creds {p} should return 401, got {res.status_code}: {res.text}")
            self.assertIn("Invalid UID or password", res.json().get("detail", ""))

        # 5. Oversized string payload (1 MB payload)
        large_str = "A" * 1_000_000
        oversized_uid_res = self.remote_client.post("/api/auth/login", json={"uid": large_str, "password": valid_pw})
        self.assertIn(oversized_uid_res.status_code, (400, 401, 413, 422), "1MB UID payload must not crash server")

        oversized_pw_res = self.remote_client.post("/api/auth/login", json={"uid": valid_uid, "password": large_str})
        self.assertIn(oversized_pw_res.status_code, (400, 401, 413, 422), "1MB Password payload must not crash server")

        # 6. Malformed JSON and raw byte bodies
        malformed_json_res = self.remote_client.post(
            "/api/auth/login",
            content=b'{"uid": "12345", "password": unquoted_value}',
            headers={"Content-Type": "application/json"}
        )
        self.assertIn(malformed_json_res.status_code, (400, 422), "Malformed JSON body must return 400/422")

        binary_body_res = self.remote_client.post(
            "/api/auth/login",
            content=b'\x00\x01\x02\xff\xfe\xfd\xaa\xbb',
            headers={"Content-Type": "application/json"}
        )
        self.assertIn(binary_body_res.status_code, (400, 422), "Binary body must return 400/422")

        # 7. Successful login with valid credentials
        valid_res = self.remote_client.post("/api/auth/login", json={"uid": valid_uid, "password": valid_pw})
        self.assertEqual(valid_res.status_code, 200, f"Valid login failed: {valid_res.text}")
        data = valid_res.json()
        self.assertTrue(data.get("success"))
        session_token = data.get("session_token")
        self.assertIsNotNone(session_token)
        self.assertTrue(session_token.startswith("ads_"))
        self.assertEqual(len(session_token), 36)

        # 8. Tolerance of whitespace in valid credentials
        ws_res = self.remote_client.post("/api/auth/login", json={"uid": f"  {valid_uid}  ", "password": f"  {valid_pw}  "})
        self.assertEqual(ws_res.status_code, 200, "Valid login with padded whitespace should succeed")

        # 9. Verify authenticated access to protected endpoints
        headers_bearer = {"Authorization": f"Bearer {session_token}"}
        headers_custom = {"X-Session-Token": session_token}
        for endpoint in ["/api/folders", "/api/shared-folders", "/api/transfers"]:
            # Remote client without auth -> 401
            self.assertEqual(self.remote_client.get(endpoint).status_code, 401)
            # Remote client with Bearer auth -> 200
            self.assertEqual(self.remote_client.get(endpoint, headers=headers_bearer).status_code, 200)
            # Remote client with X-Session-Token auth -> 200
            self.assertEqual(self.remote_client.get(endpoint, headers=headers_custom).status_code, 200)

        # 10. Logout and session invalidation
        logout_res = self.remote_client.post("/api/auth/logout", headers=headers_bearer)
        self.assertEqual(logout_res.status_code, 200)
        self.assertTrue(logout_res.json().get("success"))

        # After logout, token should be invalid immediately
        self.assertEqual(self.remote_client.get("/api/transfers", headers=headers_bearer).status_code, 401)

        print("\n[SUITE 4 PASS] Login endpoint fuzzing and boundary test passed: all 10 fuzzing scenarios validated with 0 crashes (no 500s).")


if __name__ == "__main__":
    unittest.main(verbosity=2)
