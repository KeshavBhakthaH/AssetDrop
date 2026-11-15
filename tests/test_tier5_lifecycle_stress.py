"""
tests/test_tier5_lifecycle_stress.py — Tier 5 Full-System Lifecycle Stress Testing.

Mandate from DISPATCH.md:
1. Multi-Device Simultaneous Session Lifecycle:
   - Simultaneous PC workstation polling /api/transfers every 100ms.
   - 5 mobile clients authenticating via POST /api/auth/login, fetching destination folders
     via GET /api/shared-folders, and submitting queue tasks concurrently.
   - Measure queue ingestion response latency under this load — verify average latency < 50ms.
   - Perform clean logout/session revocation on 2 mobile clients — verify revoked tokens are
     immediately rejected with HTTP 401.
2. Route Parity & Viewport Integrity:
   - Probe GET / with 30 desktop User-Agents — all must receive static/pc.html.
   - Probe GET / with 30 mobile User-Agents — all must receive static/mobile.html.
   - Probe GET /pc and GET /mobile directly — verify correct documents served.
3. Verify python verify_e2e.py passes 102/102 test cases with exit code 0.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import sys
import threading
import time
import unittest
from typing import Dict, List, Tuple

import anyio.from_thread

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Silence noisy logging during stress tests
logging.basicConfig(level=logging.WARNING)
for log_name in ("assetdrop", "httpx", "httpx2", "httpcore"):
    logging.getLogger(log_name).setLevel(logging.WARNING)

from starlette.testclient import TestClient

import server
from core.auth import clear_all_sessions, get_active_session_count, verify_session_token
from core.config import derive_server_uid, generate_connection_password
from core.queue_manager import get_queue_manager

# ---------------------------------------------------------------------------
# Test Data: 30 Desktop User Agents
# ---------------------------------------------------------------------------
DESKTOP_USER_AGENTS = [
    # Windows Chrome & Edge
    ("Win11_Chrome_122", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    ("Win10_Chrome_121", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"),
    ("Win11_Edge_122", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"),
    ("Win10_Edge_121", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0"),
    # Windows Firefox
    ("Win11_Firefox_123", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0"),
    ("Win10_Firefox_ESR", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20100101 Firefox/115.0"),
    # macOS Browsers
    ("macOS_Chrome_122", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    ("macOS_Safari_17_3", "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15"),
    ("macOS_Safari_16_5", "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15"),
    ("macOS_Edge_122", "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"),
    ("macOS_Firefox_123", "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:123.0) Gecko/20100101 Firefox/123.0"),
    ("macOS_Arc", "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Arc/1.32.0"),
    ("macOS_Opera_108", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 OPR/108.0.0.0"),
    # Linux Browsers
    ("Ubuntu_Firefox_123", "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0"),
    ("Linux_Chrome_122", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    ("Fedora_Firefox_122", "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0"),
    ("Debian_Chromium_121", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Chromium/121.0.0.0"),
    ("Arch_Chrome_122", "Mozilla/5.0 (X11; Arch Linux; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    ("FreeBSD_Chrome_122", "Mozilla/5.0 (X11; FreeBSD amd64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    # ChromeOS & Specialty Desktop
    ("ChromeOS_122", "Mozilla/5.0 (X11; CrOS x86_64 15662.76.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    ("Win11_Opera_108", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 OPR/108.0.0.0"),
    ("Win11_Brave_1_63", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Brave/1.63.162"),
    ("Win11_Vivaldi_6_6", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Vivaldi/6.6.3271.45"),
    ("Win_TorBrowser_13", "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0 TorBrowser/13.0"),
    ("Linux_TorBrowser_13", "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0 TorBrowser/13.0"),
    ("Win10_Yandex_24", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 YaBrowser/24.1.0.0 Safari/537.36"),
    ("Win_IE11_Desktop", "Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Gecko"),
    ("Lynx_Terminal_Browser", "Lynx/2.8.9rel.1 libwww-FM/2.14 SSL-MM/1.4.1 GNUTLS/3.6.13"),
    ("cURL_CLI", "curl/8.4.0"),
    ("PyWebView_Desktop_Host", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 AssetDropDesktop/1.0"),
]

# ---------------------------------------------------------------------------
# Test Data: 30 Mobile User Agents
# ---------------------------------------------------------------------------
MOBILE_USER_AGENTS = [
    # Android Flagships & Popular Phones
    ("Pixel_8_Android_14", "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36"),
    ("Samsung_S23_SamsungBrowser", "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36"),
    ("Samsung_S24_Ultra_Chrome", "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36"),
    ("Xiaomi_Redmi_Chrome", "Mozilla/5.0 (Linux; Android 12; 2201116SG) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.178 Mobile Safari/537.36"),
    ("OnePlus_11_Chrome", "Mozilla/5.0 (Linux; Android 13; CPH2449) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.143 Mobile Safari/537.36"),
    ("Moto_G_Power_Chrome", "Mozilla/5.0 (Linux; Android 11; moto g power (2021)) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36"),
    ("Android_Firefox_123", "Mozilla/5.0 (Android 14; Mobile; rv:123.0) Gecko/123.0 Firefox/123.0"),
    ("Android_Opera_Mobile", "Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.143 Mobile Safari/537.36 OPR/79.2.4195.77259"),
    ("Android_UC_Browser", "Mozilla/5.0 (Linux; U; Android 12; en-US; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/78.0.3904.108 UCBrowser/13.4.0.1306 Mobile Safari/537.36"),
    ("Android_Brave_Mobile", "Mozilla/5.0 (Linux; Android 13; Pixel 7 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36 Brave/1.63.162"),
    ("Android_DuckDuckGo", "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36 DuckDuckGo/5"),
    ("Android_VivoBrowser", "Mozilla/5.0 (Linux; Android 10; V2027) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.5304.141 Mobile Safari/537.36 VivoBrowser/12.3.1.0"),
    ("Android_OppoBrowser", "Mozilla/5.0 (Linux; Android 13; CPH2371) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.193 Mobile Safari/537.36 HeyTapBrowser/45.8.7.1"),
    ("Android_Edge_Mobile", "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36 EdgA/122.0.2365.48"),
    ("Android_WebView_Generic", "Mozilla/5.0 (Linux; U; Android 13; en-US; SM-A336B Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/122.0.6261.64 Mobile Safari/537.36"),
    # iOS iPhones
    ("iPhone_15_Pro_Safari", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"),
    ("iPhone_14_CriOS", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/122.0.6261.62 Mobile/15E148 Safari/604.1"),
    ("iPhone_13_FxiOS", "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/123.0 Mobile/15E148 Safari/605.1.15"),
    ("iPhone_15_EdgiOS", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 EdgiOS/122.0.2365.57 Mobile/15E148 Safari/605.1.15"),
    ("iPhone_SE_Safari", "Mozilla/5.0 (iPhone; CPU iPhone OS 15_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Mobile/15E148 Safari/604.1"),
    # iOS iPads & iPod
    ("iPad_Pro_Safari", "Mozilla/5.0 (iPad; CPU OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"),
    ("iPad_Air_CriOS", "Mozilla/5.0 (iPad; CPU OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/122.0.6261.62 Mobile/15E148 Safari/604.1"),
    ("iPad_Mini_Safari", "Mozilla/5.0 (iPad; CPU OS 15_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.7 Mobile/15E148 Safari/604.1"),
    ("iPod_Touch_7thGen", "Mozilla/5.0 (iPod touch; CPU iPhone OS 15_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1"),
    # Windows Phone & webOS
    ("WinPhone_10_Lumia_950", "Mozilla/5.0 (Windows Phone 10.0; Android 6.0.1; Microsoft; Lumia 950) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/52.0.2743.116 Mobile Safari/537.36 Edge/15.15254"),
    ("WinPhone_8_1_Lumia_635", "Mozilla/5.0 (Mobile; Windows Phone 8.1; Android 4.0; ARM; Trident/7.0; Touch; rv:11.0; IEMobile/11.0; NOKIA; Lumia 635) like Gecko"),
    ("webOS_Palm_Pre", "Mozilla/5.0 (webOS/1.4.5; U; en-US) AppleWebKit/532.2 (KHTML, like Gecko) Version/1.0 Safari/532.2 Pre/1.0"),
    ("Sony_Xperia_1_V_Android_14", "Mozilla/5.0 (Linux; Android 14; XQ-DQ72) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36"),
    ("Android_Tablet_SM_X910", "Mozilla/5.0 (Linux; Android 14; SM-X910) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Safari/537.36"),
    ("Capacitor_Android_App", "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/UD1A.230803.041; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.43 Mobile Safari/537.36 AssetDropCapacitor/1.0"),
]


class TestTier5LifecycleStress(unittest.TestCase):
    """
    Tier 5: Multi-Device Lifecycle, Route Parity & SLA Stress Test Suite.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)
        cls.qm = get_queue_manager()
        cls.qm.clear_history()
        cls.orig_worker = cls.qm._worker_func
        cls.qm._worker_func = lambda job_id, url, target_dir, format_type: "stress_test_video.mp4"
        creds = server.init_server_credentials()
        cls.uid = creds["uid"]
        cls.password = creds["password"]

        # Pre-warm AnyIO portal and Starlette routing pipeline
        cls.client.get("/api/transfers")
        cls.client.get("/pc")
        cls.client.get("/mobile")

    @classmethod
    def tearDownClass(cls):
        cls.qm._worker_func = cls.orig_worker
        cls.qm.clear_history()
        clear_all_sessions()

    # -------------------------------------------------------------------------
    # PART 1: Multi-Device Simultaneous Session Lifecycle
    # -------------------------------------------------------------------------
    def test_multi_device_lifecycle_and_ingestion_sla(self):
        """
        Lifecycle stress test:
        - 1 PC workstation continuously polling /api/transfers every 100ms.
        - 5 mobile clients:
          1. Concurrently authenticate via POST /api/auth/login.
          2. Concurrently fetch folders via GET /api/shared-folders.
          3. Concurrently submit 5 queue tasks each (25 total tasks) under continuous PC polling load.
          4. Verify average queue ingestion latency strictly < 50ms.
          5. Perform clean logout on 2 mobile clients and verify immediate 401 rejection.
          6. Verify remaining 3 mobile clients continue operating seamlessly.
        """
        # Step 0: Ensure fresh session state
        clear_all_sessions()
        self.assertEqual(get_active_session_count(), 0)

        # Background PC workstation poller
        pc_polls: List[Tuple[float, int, float]] = []  # (timestamp, status_code, elapsed_ms)
        pc_stop_event = threading.Event()
        pc_client = TestClient(server.app, client=("127.0.0.1", 52100))

        def pc_poller():
            with anyio.from_thread.start_blocking_portal(**pc_client.async_backend) as portal:
                pc_client.portal = portal
                try:
                    while not pc_stop_event.is_set():
                        t0 = time.perf_counter()
                        resp = pc_client.get("/api/transfers")
                        elapsed_ms = (time.perf_counter() - t0) * 1000.0
                        pc_polls.append((time.time(), resp.status_code, elapsed_ms))
                        time.sleep(0.1)  # 100ms polling interval
                finally:
                    pc_client.portal = None

        pc_thread = threading.Thread(target=pc_poller, daemon=True)
        pc_thread.start()

        try:
            # Let PC polling run for at least 2 ticks
            time.sleep(0.2)

            # Define 5 mobile client identities
            mobile_clients = [
                {
                    "id": f"mobile_client_{i+1}",
                    "ip": f"192.168.1.{101 + i}",
                    "client": TestClient(server.app, client=(f"192.168.1.{101 + i}", 50000 + i)),
                    "token": None,
                }
                for i in range(5)
            ]

            # -----------------------------------------------------------------
            # Phase A: 5 Mobile Clients Concurrently Authenticate
            # -----------------------------------------------------------------
            def mobile_login(client_info: dict) -> Tuple[str, int, str]:
                c = client_info["client"]
                resp = c.post("/api/auth/login", json={"uid": self.uid, "password": self.password})
                token = resp.json().get("session_token", "") if resp.status_code == 200 else ""
                return client_info["id"], resp.status_code, token

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                login_results = list(executor.map(mobile_login, mobile_clients))

            active_tokens = []
            for client_id, status_code, token in login_results:
                self.assertEqual(status_code, 200, f"Client {client_id} failed login: status {status_code}")
                self.assertTrue(token.startswith("ads_"), f"Client {client_id} invalid token: {token}")
                self.assertTrue(verify_session_token(token))
                active_tokens.append(token)
                # Assign token to client record
                for mc in mobile_clients:
                    if mc["id"] == client_id:
                        mc["token"] = token

            self.assertEqual(len(set(active_tokens)), 5, "Tokens must be unique per client session")
            self.assertEqual(get_active_session_count(), 5)

            # -----------------------------------------------------------------
            # Phase B: 5 Mobile Clients Concurrently Query Shared Folders
            # -----------------------------------------------------------------
            def mobile_fetch_folders(client_info: dict) -> Tuple[str, int, list]:
                c = client_info["client"]
                headers = {"Authorization": f"Bearer {client_info['token']}"}
                resp = c.get("/api/shared-folders", headers=headers)
                folders = resp.json().get("folders", []) if resp.status_code == 200 else []
                return client_info["id"], resp.status_code, folders

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                folder_results = list(executor.map(mobile_fetch_folders, mobile_clients))

            for client_id, status_code, folders in folder_results:
                self.assertEqual(status_code, 200, f"Client {client_id} failed GET /api/shared-folders")
                self.assertGreater(len(folders), 0, f"Client {client_id} received empty shared folders")
                # Ensure phone format (id and name only, no server filesystem paths leaked)
                for f in folders:
                    self.assertIn("id", f)
                    self.assertIn("name", f)
                    self.assertNotIn("path", f, f"Remote client {client_id} leaked absolute filesystem path!")

            # -----------------------------------------------------------------
            # Phase C: Concurrent Ingestion Burst Under PC Polling Load
            # 5 clients submit 5 queue tasks each = 25 concurrent submissions
            # Verify average latency < 50ms SLA
            # -----------------------------------------------------------------
            task_specs = []
            for i, mc in enumerate(mobile_clients):
                for task_idx in range(5):
                    task_specs.append({
                        "client": mc["client"],
                        "token": mc["token"],
                        "client_id": mc["id"],
                        "url": f"https://youtu.be/stress_c{i+1}_t{task_idx+1}",
                        "folder_key": "B-Roll (General)",
                        "format_type": "video" if task_idx % 2 == 0 else "audio",
                    })

            # Prime AnyIO blocking portal for the shared test client backend
            queue_latencies: List[float] = []
            queue_job_ids: List[str] = []
            queue_statuses: List[int] = []

            # We use a ThreadPoolExecutor with persistent portals
            def submit_task(spec: dict) -> Tuple[int, str, float]:
                c = spec["client"]
                headers = {"Authorization": f"Bearer {spec['token']}"}
                payload = {
                    "url": spec["url"],
                    "folder_key": spec["folder_key"],
                    "format_type": spec["format_type"],
                }
                t0 = time.perf_counter()
                resp = c.post("/api/queue", json=payload, headers=headers)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                job_id = resp.json().get("job_id", "") if resp.status_code == 200 else ""
                return resp.status_code, job_id, elapsed_ms

            # Prime AnyIO blocking portal for mobile clients to avoid per-request portal setup overhead on Windows
            with anyio.from_thread.start_blocking_portal(**mobile_clients[0]["client"].async_backend) as portal:
                for mc in mobile_clients:
                    mc["client"].portal = portal
                try:
                    # Prime single warm-up request across clients
                    for mc in mobile_clients:
                        mc["client"].post(
                            "/api/queue",
                            json={"url": "https://youtu.be/prime_warmup", "folder_key": "B-Roll (General)"},
                            headers={"Authorization": f"Bearer {mc['token']}"},
                        )
                    self.qm.clear_history()

                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        burst_results = list(executor.map(submit_task, task_specs))
                finally:
                    for mc in mobile_clients:
                        mc["client"].portal = None

            for status_code, job_id, elapsed_ms in burst_results:
                queue_statuses.append(status_code)
                queue_job_ids.append(job_id)
                queue_latencies.append(elapsed_ms)

            # Assertions for Ingestion Burst
            for i, st in enumerate(queue_statuses):
                self.assertEqual(st, 200, f"Task {i} failed with status {st}")
            self.assertEqual(len(set(queue_job_ids)), 25, "All 25 submitted jobs must have unique job IDs")

            avg_queue_latency = sum(queue_latencies) / len(queue_latencies)
            max_queue_latency = max(queue_latencies)
            min_queue_latency = min(queue_latencies)

            print(f"\n[STRESS SLA METRICS] Ingestion Requests: {len(queue_latencies)}")
            print(f"    Avg Latency: {avg_queue_latency:.2f} ms (SLA Target: < 50.0 ms)")
            print(f"    Min Latency: {min_queue_latency:.2f} ms")
            print(f"    Max Latency: {max_queue_latency:.2f} ms")
            self.assertLess(
                avg_queue_latency,
                50.0,
                f"Queue ingestion average latency {avg_queue_latency:.2f}ms violated <50ms SLA under multi-device load",
            )

            # -----------------------------------------------------------------
            # Phase D: Clean Logout & Token Revocation on 2 Mobile Clients
            # -----------------------------------------------------------------
            revoked_clients = [mobile_clients[0], mobile_clients[1]]
            surviving_clients = mobile_clients[2:]

            for mc in revoked_clients:
                rev_resp = mc["client"].post(
                    "/api/auth/logout",
                    headers={"Authorization": f"Bearer {mc['token']}"},
                )
                self.assertEqual(rev_resp.status_code, 200)
                self.assertTrue(rev_resp.json().get("success"))
                # Verify token removed from memory
                self.assertFalse(verify_session_token(mc["token"]))

            self.assertEqual(get_active_session_count(), 3)

            # Immediately test revoked tokens — MUST return 401
            for mc in revoked_clients:
                # 1. Queue submission with revoked token
                rej_queue = mc["client"].post(
                    "/api/queue",
                    json={"url": "https://youtu.be/revoked_test", "folder_key": "B-Roll (General)"},
                    headers={"Authorization": f"Bearer {mc['token']}"},
                )
                self.assertEqual(
                    rej_queue.status_code,
                    401,
                    f"Revoked token for {mc['id']} was NOT rejected on /api/queue! Status: {rej_queue.status_code}",
                )

                # 2. Shared folders with revoked token
                rej_folders = mc["client"].get(
                    "/api/shared-folders",
                    headers={"Authorization": f"Bearer {mc['token']}"},
                )
                self.assertEqual(
                    rej_folders.status_code,
                    401,
                    f"Revoked token for {mc['id']} was NOT rejected on /api/shared-folders! Status: {rej_folders.status_code}",
                )

            # -----------------------------------------------------------------
            # Phase E: Remaining 3 Mobile Clients Continue Uninterrupted
            # -----------------------------------------------------------------
            for mc in surviving_clients:
                # Verify folders
                ok_folders = mc["client"].get(
                    "/api/shared-folders",
                    headers={"Authorization": f"Bearer {mc['token']}"},
                )
                self.assertEqual(ok_folders.status_code, 200, f"Active client {mc['id']} affected by peer revocations")

                # Verify queue submission
                ok_queue = mc["client"].post(
                    "/api/queue",
                    json={"url": f"https://youtu.be/survivor_{mc['id']}", "folder_key": "B-Roll (General)"},
                    headers={"Authorization": f"Bearer {mc['token']}"},
                )
                self.assertEqual(ok_queue.status_code, 200, f"Active client {mc['id']} queue submission failed")
                self.assertEqual(ok_queue.json()["status"], "queued")

            # Allow PC poller to capture at least 10 continuous 100ms cycles of telemetry
            t_wait_start = time.time()
            while len(pc_polls) < 10 and (time.time() - t_wait_start < 2.0):
                time.sleep(0.05)

        finally:
            # Step F: Stop PC Poller and inspect stats
            pc_stop_event.set()
            pc_thread.join(timeout=2.0)

        # Evaluate PC poller stats
        self.assertGreater(len(pc_polls), 5, "PC polling thread did not execute sufficient polls")
        pc_poll_statuses = [st for _, st, _ in pc_polls]
        pc_poll_latencies = [lat for _, _, lat in pc_polls]
        self.assertTrue(all(st == 200 for st in pc_poll_statuses), f"PC poll experienced non-200 status: {set(pc_poll_statuses)}")
        avg_pc_poll_ms = sum(pc_poll_latencies) / len(pc_poll_latencies)
        print(f"\n[PC WORKSTATION POLLER METRICS] Total Polls: {len(pc_polls)}")
        print(f"    100% Success (HTTP 200): {all(st == 200 for st in pc_poll_statuses)}")
        print(f"    Avg Poll Latency: {avg_pc_poll_ms:.2f} ms")
        print(f"    Max Poll Latency: {max(pc_poll_latencies):.2f} ms")

    # -------------------------------------------------------------------------
    # PART 2: Route Parity & Viewport Integrity (30 Desktop + 30 Mobile UAs)
    # -------------------------------------------------------------------------
    def test_desktop_user_agents_route_parity_30(self):
        """
        Verify that 30 distinct desktop User-Agents probing GET / all receive static/pc.html.
        """
        pc_html_marker = "AssetDrop Workstation"
        tested_count = 0

        for label, ua in DESKTOP_USER_AGENTS:
            resp = self.client.get("/", headers={"User-Agent": ua})
            self.assertEqual(resp.status_code, 200, f"Desktop UA [{label}] failed with status {resp.status_code}")
            content_type = resp.headers.get("content-type", "")
            self.assertIn("text/html", content_type, f"Desktop UA [{label}] content-type not text/html: {content_type}")
            text = resp.text
            self.assertIn(
                pc_html_marker,
                text,
                f"Desktop UA [{label}] did not receive PC dashboard! Sample: {text[:200]}",
            )
            # Ensure mobile container is NOT served
            self.assertNotIn('id="view-mobile"', text, f"Desktop UA [{label}] erroneously received mobile.html!")
            tested_count += 1

        self.assertEqual(tested_count, 30, "Exactly 30 desktop User-Agents must be verified")
        print(f"\n[UA ROUTING METRICS] 30/30 Desktop User-Agents verified -> static/pc.html served with 100% parity.")

    def test_mobile_user_agents_route_parity_30(self):
        """
        Verify that 30 distinct mobile User-Agents probing GET / all receive static/mobile.html.
        """
        mobile_html_marker = "view-mobile"
        tested_count = 0

        for label, ua in MOBILE_USER_AGENTS:
            resp = self.client.get("/", headers={"User-Agent": ua})
            self.assertEqual(resp.status_code, 200, f"Mobile UA [{label}] failed with status {resp.status_code}")
            content_type = resp.headers.get("content-type", "")
            self.assertIn("text/html", content_type, f"Mobile UA [{label}] content-type not text/html: {content_type}")
            text = resp.text
            self.assertIn(
                mobile_html_marker,
                text,
                f"Mobile UA [{label}] did not receive Mobile client! Sample: {text[:200]}",
            )
            # Ensure PC container is NOT served
            self.assertNotIn("pc-container", text, f"Mobile UA [{label}] erroneously received pc.html!")
            tested_count += 1

        self.assertEqual(tested_count, 30, "Exactly 30 mobile User-Agents must be verified")
        print(f"\n[UA ROUTING METRICS] 30/30 Mobile User-Agents verified -> static/mobile.html served with 100% parity.")

    def test_direct_route_inspection(self):
        """
        Verify direct canonical and extension routes:
        GET /pc, GET /pc.html -> static/pc.html
        GET /mobile, GET /mobile.html -> static/mobile.html
        """
        # 1. GET /pc
        r_pc = self.client.get("/pc")
        self.assertEqual(r_pc.status_code, 200)
        self.assertIn("AssetDrop Workstation", r_pc.text)
        self.assertNotIn('id="view-mobile"', r_pc.text)

        # 2. GET /pc.html
        r_pc_ext = self.client.get("/pc.html")
        self.assertEqual(r_pc_ext.status_code, 200)
        self.assertIn("AssetDrop Workstation", r_pc_ext.text)

        # 3. GET /mobile
        r_mob = self.client.get("/mobile")
        self.assertEqual(r_mob.status_code, 200)
        self.assertIn("view-mobile", r_mob.text)
        self.assertNotIn("pc-container", r_mob.text)

        # 4. GET /mobile.html
        r_mob_ext = self.client.get("/mobile.html")
        self.assertEqual(r_mob_ext.status_code, 200)
        self.assertIn("view-mobile", r_mob_ext.text)

        print("\n[DIRECT ROUTE METRICS] /pc, /pc.html, /mobile, /mobile.html verified directly.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
