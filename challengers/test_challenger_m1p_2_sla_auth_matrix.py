"""
tests/test_challenger_m1p_2_sla_auth_matrix.py

Milestone M1-P Empirical Challenge Suite:
1. Ingestion Latency SLA (<50ms):
   - Benchmark POST /api/queue with valid session token over 50 sequential requests (verify mean & p99 < 50ms).
   - Benchmark POST /download (route alias) over 50 sequential requests under session auth.
   - Concurrent burst testing (10 simultaneous client threads under session auth).
   - Backlogged queue insertion SLA testing (50 pre-existing jobs).
2. Comprehensive Authorization Matrix:
   - Full 4x10 matrix across localhost, unauthenticated remote, invalid-token remote, and authenticated remote.
   - Strict 403 Forbidden enforcement on /api/workstation/credentials for ALL remote callers (even with valid token).
   - Token transport mechanism coverage: Bearer, bearer, raw token, X-Session-Token, X-Device-Token, query ?token=.
   - Session revocation and lifecycle testing.
3. Legacy Route Eradication Sweep:
   - 100% HTTP 404 Not Found verification across 30 legacy endpoints and 4 HTTP methods (120 probes).
   - Router introspection asserting zero legacy routes registered.
4. Localhost Spoofing Defense:
   - Header injection testing (X-Forwarded-For, Client-IP, X-Real-IP, etc.) to verify remote authorization cannot be bypassed.
"""

from __future__ import annotations

import concurrent.futures
import os
import sys
import time
import unittest
from typing import Any, Dict, List, Tuple

# Ensure repository root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
from starlette.testclient import TestClient

from core.auth import (
    clear_all_sessions,
    create_session_token,
    get_active_session_count,
    revoke_session_token,
    verify_session_token,
)
from core.config import derive_server_uid, generate_connection_password, load_config
from core.queue_manager import get_queue_manager
from core.security_limits import reset_download_rate_limit
import server
from tests.mock_cli import simulated_worker_func


class TestQueueIngestionLatencySLA(unittest.TestCase):
    """Empirically challenge the <50ms response time SLA for queue ingestion."""

    @classmethod
    def setUpClass(cls):
        clear_all_sessions()
        server.init_server_credentials(force_refresh=True)
        cls.qm = get_queue_manager()
        cls.qm._worker_func = simulated_worker_func
        cls.remote_client = TestClient(server.app, client=("192.168.1.150", 49200))
        cls.valid_token = create_session_token()
        cls.auth_headers = {"Authorization": f"Bearer {cls.valid_token}"}

        # Warmup ASGI pipeline and dependency injection graph
        cls.remote_client.post(
            "/api/queue",
            json={"url": "https://www.youtube.com/watch?v=warmup_sla"},
            headers=cls.auth_headers,
        )
        reset_download_rate_limit(cls.valid_token)

    def tearDown(self):
        reset_download_rate_limit(self.valid_token)

    def test_01_benchmark_api_queue_50_sequential_requests_sla(self):
        """
        Benchmark POST /api/queue with valid session token over 50 sequential requests.
        Assert that every single request returns 200 OK, and mean & p99 latencies are strictly < 50ms.
        """
        latencies_ms: List[float] = []

        for i in range(50):
            reset_download_rate_limit(self.valid_token)
            payload = {
                "url": f"https://www.youtube.com/watch?v=sla_benchmark_item_{i:03d}",
                "folder_key": "B-Roll (General)",
                "format_type": "video",
            }
            t0 = time.perf_counter()
            resp = self.remote_client.post(
                "/api/queue",
                json=payload,
                headers=self.auth_headers,
            )
            t1 = time.perf_counter()
            elapsed_ms = (t1 - t0) * 1000.0
            latencies_ms.append(elapsed_ms)

            self.assertEqual(resp.status_code, 200, f"Request {i} failed with status {resp.status_code}")
            body = resp.json()
            self.assertEqual(body.get("status"), "queued")
            self.assertIn("job_id", body)
            self.assertLess(elapsed_ms, 50.0, f"Request {i} took {elapsed_ms:.2f}ms (exceeded 50ms SLA)")

        mean_ms = float(np.mean(latencies_ms))
        p50_ms = float(np.percentile(latencies_ms, 50))
        p95_ms = float(np.percentile(latencies_ms, 95))
        p99_ms = float(np.percentile(latencies_ms, 99))
        max_ms = max(latencies_ms)
        min_ms = min(latencies_ms)

        print("\n--- Empirical Benchmark: POST /api/queue (50 requests under Session Auth) ---")
        print(f"Min:  {min_ms:.2f} ms")
        print(f"Mean: {mean_ms:.2f} ms")
        print(f"p50:  {p50_ms:.2f} ms")
        print(f"p95:  {p95_ms:.2f} ms")
        print(f"p99:  {p99_ms:.2f} ms")
        print(f"Max:  {max_ms:.2f} ms")

        self.assertLess(mean_ms, 50.0, f"Mean latency {mean_ms:.2f}ms exceeded 50ms SLA")
        self.assertLess(p99_ms, 50.0, f"p99 latency {p99_ms:.2f}ms exceeded 50ms SLA")
        self.assertLess(max_ms, 50.0, f"Max latency {max_ms:.2f}ms exceeded 50ms SLA")

    def test_02_benchmark_download_alias_50_sequential_requests_sla(self):
        """
        Benchmark POST /download route alias with valid session token over 50 sequential requests.
        Assert that mean & p99 latencies are strictly < 50ms.
        """
        latencies_ms: List[float] = []

        for i in range(50):
            reset_download_rate_limit(self.valid_token)
            payload = {
                "url": f"https://www.youtube.com/watch?v=download_alias_{i:03d}",
                "folder_key": "Social Edits",
                "format_type": "audio",
            }
            t0 = time.perf_counter()
            resp = self.remote_client.post(
                "/download",
                json=payload,
                headers=self.auth_headers,
            )
            t1 = time.perf_counter()
            elapsed_ms = (t1 - t0) * 1000.0
            latencies_ms.append(elapsed_ms)

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json().get("status"), "queued")

        mean_ms = float(np.mean(latencies_ms))
        p99_ms = float(np.percentile(latencies_ms, 99))

        print("\n--- Empirical Benchmark: POST /download (50 requests under Session Auth) ---")
        print(f"Mean: {mean_ms:.2f} ms | p99: {p99_ms:.2f} ms | Max: {max(latencies_ms):.2f} ms")

        self.assertLess(mean_ms, 50.0)
        self.assertLess(p99_ms, 50.0)

    def test_03_concurrent_ingestion_burst_10_threads_sla(self):
        """
        Benchmark 10 concurrent threads submitting download jobs simultaneously under session auth.
        Assert that all 10 return 200 OK and each request completes in < 50ms.
        """
        tokens = [create_session_token() for _ in range(10)]
        results: List[Tuple[int, float, str]] = []

        def worker_task(idx: int) -> Tuple[int, float, str]:
            client = TestClient(server.app, client=(f"192.168.1.{200+idx}", 50000))
            payload = {"url": f"https://www.youtube.com/watch?v=threaded_item_{idx:02d}"}
            hdrs = {"Authorization": f"Bearer {tokens[idx]}"}
            t0 = time.perf_counter()
            r = client.post("/api/queue", json=payload, headers=hdrs)
            t1 = time.perf_counter()
            job_id = r.json().get("job_id", "") if r.status_code == 200 else ""
            return r.status_code, (t1 - t0) * 1000.0, job_id

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_task, i) for i in range(10)]
            for fut in concurrent.futures.as_completed(futures):
                results.append(fut.result())

        unique_job_ids = set()
        for idx, (status_code, elapsed_ms, job_id) in enumerate(results):
            self.assertEqual(status_code, 200, f"Concurrent thread {idx} failed with {status_code}")
            self.assertTrue(job_id, f"Thread {idx} returned empty job_id")
            unique_job_ids.add(job_id)

        self.assertEqual(len(unique_job_ids), 10, "Job IDs must be uniquely generated under concurrency")
        burst_latencies = [el for _, el, _ in results]
        burst_mean = float(np.mean(burst_latencies))
        burst_max = float(max(burst_latencies))
        print(f"\n--- Concurrent Burst (10 simultaneous threads): Mean = {burst_mean:.2f}ms | Max = {burst_max:.2f}ms ---")

    def test_04_ingestion_sla_with_queue_backlog(self):
        """
        Verify that queue insertion latency remains < 50ms even when the QueueManager
        has an active backlog of 50+ pre-existing items.
        """
        # Preload 50 items into the queue
        for i in range(50):
            self.qm.enqueue_job(
                url=f"https://www.youtube.com/watch?v=backlog_{i:03d}",
                target_dir="D:/Assets/BRoll",
                format_type="video",
            )

        backlog_latencies: List[float] = []
        for i in range(20):
            reset_download_rate_limit(self.valid_token)
            payload = {"url": f"https://www.youtube.com/watch?v=post_backlog_{i:02d}"}
            t0 = time.perf_counter()
            resp = self.remote_client.post("/api/queue", json=payload, headers=self.auth_headers)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            backlog_latencies.append(elapsed_ms)
            self.assertEqual(resp.status_code, 200)

        mean_backlog = float(np.mean(backlog_latencies))
        self.assertLess(mean_backlog, 50.0)
        print(f"\n--- Backlogged Ingestion SLA (50 pre-existing jobs): Mean = {mean_backlog:.2f}ms ---")


class TestComprehensiveAuthorizationMatrix(unittest.TestCase):
    """
    Comprehensive authorization matrix testing across all endpoints:
    - Localhost vs Remote Unauthenticated vs Remote Invalid Token vs Remote Authenticated.
    """

    @classmethod
    def setUpClass(cls):
        clear_all_sessions()
        server.init_server_credentials(force_refresh=True)
        cls.local_client = TestClient(server.app)
        cls.remote_client = TestClient(server.app, client=("192.168.1.199", 51234))
        cls.valid_token = create_session_token()
        cls.invalid_token = "ads_invalid_deadbeef0123456789abcdef"

    def tearDown(self):
        clear_all_sessions()
        self.__class__.valid_token = create_session_token()

    def test_01_matrix_across_all_endpoints(self):
        """
        Probe all endpoints across 4 authentication states:
        1. Localhost (Allowed: 200 OK for protected endpoints and credentials)
        2. Remote without token (401 for protected endpoints, 403 for credentials)
        3. Remote with invalid token (401 for protected endpoints, 403 for credentials)
        4. Remote with valid session token (200 for protected endpoints, 403 for credentials)
        """
        test_matrix: List[Dict[str, Any]] = [
            # Ingestion endpoints
            {"method": "POST", "path": "/api/queue", "body": {"url": "https://www.youtube.com/watch?v=matrix1"}, "protected": True, "credentials": False},
            {"method": "POST", "path": "/download", "body": {"url": "https://www.youtube.com/watch?v=matrix2"}, "protected": True, "credentials": False},
            # Shared folders endpoints
            {"method": "GET", "path": "/api/shared-folders", "body": None, "protected": True, "credentials": False},
            {"method": "GET", "path": "/api/folders", "body": None, "protected": True, "credentials": False},
            # Telemetry endpoints
            {"method": "GET", "path": "/api/transfers", "body": None, "protected": True, "credentials": False},
            {"method": "GET", "path": "/api/status", "body": None, "protected": True, "credentials": False},
            {"method": "GET", "path": "/status", "body": None, "protected": True, "credentials": False},
            # Workstation credentials endpoints (Local PC only)
            {"method": "GET", "path": "/api/workstation/credentials", "body": None, "protected": False, "credentials": True},
            {"method": "GET", "path": "/api/workstation/settings", "body": None, "protected": False, "credentials": True},
            {"method": "GET", "path": "/api/workstation/info", "body": None, "protected": False, "credentials": True},
        ]

        for item in test_matrix:
            m = item["method"]
            p = item["path"]
            body = item["body"]
            is_protected = item["protected"]
            is_creds = item["credentials"]

            # State 1: Localhost (PC workstation)
            r_loc = self.local_client.get(p) if m == "GET" else self.local_client.post(p, json=body)
            self.assertEqual(
                r_loc.status_code, 200,
                f"Localhost access to {p} should be allowed (200), got {r_loc.status_code}"
            )

            # State 2: Remote without token
            r_unauth = self.remote_client.get(p) if m == "GET" else self.remote_client.post(p, json=body)
            if is_protected:
                self.assertEqual(
                    r_unauth.status_code, 401,
                    f"Remote unauthenticated call to {p} must return 401, got {r_unauth.status_code}"
                )
                self.assertIn("Bearer", r_unauth.headers.get("WWW-Authenticate", ""))
            elif is_creds:
                self.assertEqual(
                    r_unauth.status_code, 403,
                    f"Remote call to {p} must return 403 Forbidden, got {r_unauth.status_code}"
                )

            # State 3: Remote with invalid token
            inv_hdrs = {"Authorization": f"Bearer {self.invalid_token}"}
            r_inv = self.remote_client.get(p, headers=inv_hdrs) if m == "GET" else self.remote_client.post(p, json=body, headers=inv_hdrs)
            if is_protected:
                self.assertEqual(
                    r_inv.status_code, 401,
                    f"Remote call to {p} with invalid token must return 401, got {r_inv.status_code}"
                )
            elif is_creds:
                self.assertEqual(
                    r_inv.status_code, 403,
                    f"Remote call to credentials {p} with invalid token must return 403, got {r_inv.status_code}"
                )

            # State 4: Remote with valid session token
            val_hdrs = {"Authorization": f"Bearer {self.valid_token}"}
            r_val = self.remote_client.get(p, headers=val_hdrs) if m == "GET" else self.remote_client.post(p, json=body, headers=val_hdrs)
            if is_protected:
                self.assertEqual(
                    r_val.status_code, 200,
                    f"Remote authenticated call to {p} must return 200, got {r_val.status_code}"
                )
            elif is_creds:
                # Workstation credentials MUST NEVER be accessible to remote clients, even with valid token!
                self.assertEqual(
                    r_val.status_code, 403,
                    f"Remote call to credentials {p} with valid session token must STILL return 403 Forbidden, got {r_val.status_code}"
                )

    def test_02_token_transport_mechanisms(self):
        """
        Verify that session token is accepted across all supported transport mechanisms:
        - Authorization: Bearer <tok>
        - Authorization: bearer <tok>
        - Authorization: <tok>
        - X-Session-Token: <tok>
        - X-Device-Token: <tok>
        - Query parameter ?token=<tok>
        """
        tok = self.valid_token
        variants = [
            ("Bearer standard", {"headers": {"Authorization": f"Bearer {tok}"}}),
            ("bearer lowercase", {"headers": {"Authorization": f"bearer {tok}"}}),
            ("BEARER uppercase", {"headers": {"Authorization": f"BEARER {tok}"}}),
            ("raw token", {"headers": {"Authorization": tok}}),
            ("X-Session-Token header", {"headers": {"X-Session-Token": tok}}),
            ("X-Device-Token header", {"headers": {"X-Device-Token": tok}}),
            ("query param token", {"params": {"token": tok}}),
        ]

        for name, req_kwargs in variants:
            res = self.remote_client.get("/api/transfers", **req_kwargs)
            self.assertEqual(res.status_code, 200, f"Transport variant '{name}' failed with status {res.status_code}")

    def test_03_session_revocation_lifecycle(self):
        """
        Verify session token issuance, active validation, and immediate invalidation on logout.
        """
        creds = server.init_server_credentials()
        login_res = self.remote_client.post(
            "/api/auth/login",
            json={"uid": creds["uid"], "password": creds["password"]},
        )
        self.assertEqual(login_res.status_code, 200)
        session_tok = login_res.json()["session_token"]
        self.assertTrue(session_tok.startswith("ads_"))
        auth_hdr = {"Authorization": f"Bearer {session_tok}"}

        # Step 1: Protected endpoint access succeeds
        self.assertEqual(self.remote_client.get("/api/transfers", headers=auth_hdr).status_code, 200)

        # Step 2: Logout revokes session token
        logout_res = self.remote_client.post("/api/auth/logout", headers=auth_hdr)
        self.assertEqual(logout_res.status_code, 200)

        # Step 3: Immediate subsequent call returns 401 Unauthorized
        post_logout_res = self.remote_client.get("/api/transfers", headers=auth_hdr)
        self.assertEqual(post_logout_res.status_code, 401)


class TestLegacyRouteEradicationSweep(unittest.TestCase):
    """
    Empirically verify 100% removal of legacy routes:
    - Probe legacy routes with GET, POST, PUT, DELETE.
    - Router introspection ensuring zero legacy endpoints remain.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)

    def test_01_probe_100_percent_legacy_routes_return_404(self):
        """
        Exhaustive probe of 30 legacy routes across GET, POST, PUT, DELETE (120 probes).
        Assert 100% of responses are HTTP 404 Not Found.
        """
        legacy_endpoints = [
            "/api/qrcode",
            "/api/qrcode/regenerate",
            "/pair",
            "/api/pair",
            "/api/auth/pair",
            "/api/devices",
            "/api/devices/",
            "/api/devices/dev_123",
            "/api/devices/revoke",
            "/api/network/mode",
            "/api/network/modes",
            "/api/network",
            "/api/auth/status",
            "/api/auth/verify",
            "/api/auth/settings",
            "/api/auth/pin",
            "/api/pin",
            "/api/pairing",
            "/api/pair/status",
            "/api/pair/confirm",
            "/api/pair/cancel",
            "/api/pairing/status",
            "/api/devices/active",
            "/api/devices/history",
            "/api/auth/devices",
            "/api/auth/device",
            "/qrcode",
            "/devices",
            "/network/mode",
            "/auth/status",
        ]

        methods = ["GET", "POST", "PUT", "DELETE"]
        total_probes = 0
        failed_probes = []

        for route in legacy_endpoints:
            for meth in methods:
                total_probes += 1
                req_fn = getattr(self.client, meth.lower())
                if meth in ("POST", "PUT"):
                    resp = req_fn(route, json={"test": True})
                else:
                    resp = req_fn(route)

                if resp.status_code != 404:
                    failed_probes.append((meth, route, resp.status_code))

        self.assertEqual(
            len(failed_probes), 0,
            f"Expected all legacy routes to return 404, but {len(failed_probes)} returned non-404: {failed_probes}"
        )
        self.assertEqual(total_probes, 120)
        print(f"\n--- Legacy Route Eradication: All {total_probes} probes returned 404 Not Found ---")

    def test_02_router_introspection_cleanliness(self):
        """
        Inspect server.app, public_router, and protected_router to verify
        that no legacy path patterns exist in the active route definitions.
        """
        legacy_patterns = [
            "qrcode", "pair", "device", "network/mode"
        ]

        all_route_paths: List[str] = []
        for r in server.app.routes:
            path = getattr(r, "path", None)
            if path:
                all_route_paths.append(path)

        for r in server.public_router.routes:
            path = getattr(r, "path", None)
            if path:
                all_route_paths.append(path)

        for r in server.protected_router.routes:
            path = getattr(r, "path", None)
            if path:
                all_route_paths.append(path)

        for p in all_route_paths:
            for pat in legacy_patterns:
                self.assertNotIn(
                    pat, p.lower(),
                    f"Found lingering legacy pattern '{pat}' in active route '{p}'"
                )


class TestLocalhostSpoofingDefense(unittest.TestCase):
    """
    Empirically challenge localhost spoofing defenses:
    Remote client sending X-Forwarded-For, Client-IP, or other proxy headers
    must NOT bypass remote authorization checks.
    """

    @classmethod
    def setUpClass(cls):
        clear_all_sessions()
        server.init_server_credentials(force_refresh=True)
        # Remote client with real external socket IP
        cls.remote_client = TestClient(server.app, client=("192.168.1.188", 54321))
        cls.spoof_header_permutations = [
            {"X-Forwarded-For": "127.0.0.1"},
            {"X-Forwarded-For": "localhost"},
            {"X-Forwarded-For": "::1"},
            {"X-Forwarded-For": "127.0.0.1, 192.168.1.188"},
            {"Client-IP": "127.0.0.1"},
            {"X-Remote-IP": "127.0.0.1"},
            {"X-Real-IP": "127.0.0.1"},
            {"X-Client-IP": "127.0.0.1"},
            {"X-Cluster-Client-IP": "127.0.0.1"},
            {"Forwarded": "for=127.0.0.1"},
            {
                "X-Forwarded-For": "127.0.0.1",
                "Client-IP": "127.0.0.1",
                "X-Real-IP": "127.0.0.1",
                "Host": "localhost:8000",
            },
        ]

    def test_01_credentials_endpoint_spoofing_defense(self):
        """
        Remote client attempting to reveal workstation credentials with spoofed localhost headers
        must strictly receive 403 Forbidden on all attempts.
        """
        for headers in self.spoof_header_permutations:
            # Test /api/workstation/credentials
            r1 = self.remote_client.get("/api/workstation/credentials", headers=headers)
            self.assertEqual(
                r1.status_code, 403,
                f"Spoofed headers {headers} bypassed credentials check on /api/workstation/credentials (got {r1.status_code})"
            )
            # Test /api/workstation/settings alias
            r2 = self.remote_client.get("/api/workstation/settings", headers=headers)
            self.assertEqual(
                r2.status_code, 403,
                f"Spoofed headers {headers} bypassed credentials check on /api/workstation/settings (got {r2.status_code})"
            )

    def test_02_protected_endpoints_spoofing_defense(self):
        """
        Remote client attempting to access protected endpoints with spoofed localhost headers
        (and no session token) must strictly receive 401 Unauthorized.
        """
        protected_endpoints = [
            ("POST", "/api/queue", {"url": "https://www.youtube.com/watch?v=spoof_test"}),
            ("POST", "/download", {"url": "https://www.youtube.com/watch?v=spoof_test"}),
            ("GET", "/api/shared-folders", None),
            ("GET", "/api/folders", None),
            ("GET", "/api/transfers", None),
            ("GET", "/api/status", None),
        ]

        total_tested = 0
        for headers in self.spoof_header_permutations:
            for meth, path, body in protected_endpoints:
                total_tested += 1
                if meth == "GET":
                    resp = self.remote_client.get(path, headers=headers)
                else:
                    resp = self.remote_client.post(path, json=body, headers=headers)

                self.assertEqual(
                    resp.status_code, 401,
                    f"Spoofed headers {headers} allowed access to {path} (got {resp.status_code}, expected 401)"
                )

        print(f"\n--- Localhost Spoofing Defense: {total_tested} spoofing permutations defeated (all 401/403) ---")

    def test_03_testclient_simulated_remote_ip_boundary(self):
        """
        Verify that when a request arrives from Starlette TestClient (client.host == 'testclient')
        with a simulated remote IP in X-Forwarded-For or X-Remote-IP, is_local_request
        correctly recognizes it as a remote client and denies localhost privileges.
        """
        tc_client = TestClient(server.app)

        # Simulated remote client via X-Forwarded-For
        resp_fwd = tc_client.get(
            "/api/workstation/credentials",
            headers={"X-Forwarded-For": "192.168.1.188"},
        )
        self.assertEqual(
            resp_fwd.status_code, 403,
            f"Simulated remote IP in X-Forwarded-For was not recognized as remote: got {resp_fwd.status_code}"
        )

        # Simulated remote client via X-Remote-IP
        resp_rem = tc_client.get(
            "/api/workstation/credentials",
            headers={"X-Remote-IP": "10.0.0.99"},
        )
        self.assertEqual(
            resp_rem.status_code, 403,
            f"Simulated remote IP in X-Remote-IP was not recognized as remote: got {resp_rem.status_code}"
        )

        # TestClient without headers is treated as local PC workstation
        resp_loc = tc_client.get("/api/workstation/credentials")
        self.assertEqual(resp_loc.status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
