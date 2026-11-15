"""
tests/test_tier2_boundaries.py — Tier 2: Boundary Value & Adversarial Corner Cases Suite.

Tests boundary conditions, malformed inputs, command injection attempts,
directory traversal escapes, null-byte attacks, unauthorized PIN attempts,
subprocess failure capturing, and extreme filenames.

Coverage: >= 28 test cases.
Framework: Python standard library unittest + starlette.testclient.TestClient.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from starlette.testclient import TestClient

import server
from core.auth import create_session_token, revoke_session_token, verify_session_token
from core.config import add_preset, load_config, save_config, verify_pin
from core.queue_manager import get_queue_manager
from core.routing import build_download_command
from core.security_limits import (
    check_download_rate_limit,
    reset_download_rate_limit,
    sanitize_filename,
    validate_download_url,
    validate_path_containment,
)
from core.subprocess_runner import (
    ToolNotFoundError,
    execute_download_job,
    extract_error_details,
    run_command_stealth,
)
from core.traversal import browse_directory
from tests.mock_cli import MockCLIInterceptor, patch_subprocess_cli, simulated_worker_func


class TestTier2Boundaries(unittest.TestCase):
    """
    Tier 2: Boundary Value & Corner Cases Verification Suite.
    """

    @classmethod
    def setUpClass(cls):
        for log_name in ("assetdrop", "httpx", "httpx2", "httpcore"):
            logging.getLogger(log_name).setLevel(logging.WARNING)
        cls.client = TestClient(server.app)
        cls.qm = get_queue_manager()
        cls.qm._worker_func = simulated_worker_func

    @classmethod
    def tearDownClass(cls):
        t_wait = 0.0
        while cls.qm._active and t_wait < 0.3:
            time.sleep(0.02)
            t_wait += 0.02
        cls.qm.clear_history()

    def setUp(self):
        self.original_config = load_config()
        clean_cfg = dict(self.original_config)
        clean_cfg["access_pin"] = None
        save_config(clean_cfg)

    def tearDown(self):
        save_config(self.original_config)

    # -------------------------------------------------------------------------
    # 1. URL Payload Boundaries & Rejection
    # -------------------------------------------------------------------------
    def test_t2_01_empty_url_rejected(self):
        """Tier 2: Empty URL string '' is rejected with 400 or 422."""
        resp = self.client.post("/api/queue", json={"url": ""})
        self.assertIn(resp.status_code, (400, 422))

    def test_t2_02_whitespace_only_url_rejected(self):
        """Tier 2: Whitespace-only URL '    ' is rejected with 400 or 422."""
        resp = self.client.post("/api/queue", json={"url": "   \t\n  "})
        self.assertIn(resp.status_code, (400, 422))

    def test_t2_03_missing_url_field_rejected(self):
        """Tier 2: Ingest payload missing 'url' key is rejected with 422."""
        resp = self.client.post("/api/queue", json={"folder_key": "B-Roll (General)"})
        self.assertEqual(resp.status_code, 422)

    def test_t2_04_non_string_url_rejected(self):
        """Tier 2: Ingest payload with non-string URL is rejected with 422."""
        resp = self.client.post("/api/queue", json={"url": 12345678})
        self.assertEqual(resp.status_code, 422)

    def test_t2_05_extremely_long_url_handled_safely(self):
        """Tier 2: Extremely long URL (4000+ chars) is accepted and queued without crashing."""
        long_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&param=" + ("a" * 4000)
        resp = self.client.post("/api/queue", json={"url": long_url})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "queued")

    # -------------------------------------------------------------------------
    # 2. Command Injection & Subprocess Argument Safety
    # -------------------------------------------------------------------------
    def test_t2_06_command_injection_semicolon(self):
        """Tier 2: URL containing '; calc.exe' is preserved as single argument without shell execution."""
        injection_url = "https://youtube.com/watch?v=123; calc.exe"
        _, cmd = build_download_command(injection_url, "D:/Assets/BRoll")
        self.assertIn(injection_url, cmd)
        self.assertIsInstance(cmd, list)

    def test_t2_07_command_injection_ampersand(self):
        """Tier 2: URL containing '& dir & calc' is preserved as single argument."""
        injection_url = "https://youtube.com/watch?v=123&foo=bar&calc"
        _, cmd = build_download_command(injection_url, "D:/Assets/BRoll")
        self.assertIn(injection_url, cmd)

    def test_t2_08_command_injection_pipe(self):
        """Tier 2: URL containing '| whoami' is preserved safely."""
        injection_url = "https://youtube.com/watch?v=123|whoami"
        _, cmd = build_download_command(injection_url, "D:/Assets/BRoll")
        self.assertIn(injection_url, cmd)

    def test_t2_09_command_injection_backtick(self):
        """Tier 2: URL containing '`calc`' is preserved safely."""
        injection_url = "https://youtube.com/watch?v=`calc`"
        _, cmd = build_download_command(injection_url, "D:/Assets/BRoll")
        self.assertIn(injection_url, cmd)

    def test_t2_10_command_injection_newline(self):
        """Tier 2: URL with embedded newline is handled without breaking arguments."""
        injection_url = "https://youtube.com/watch?v=123\ncalc.exe"
        _, cmd = build_download_command(injection_url, "D:/Assets/BRoll")
        self.assertIn(injection_url, cmd)

    # -------------------------------------------------------------------------
    # 3. Directory Traversal & Filesystem Boundaries
    # -------------------------------------------------------------------------
    def test_t2_11_directory_traversal_double_dot(self):
        """Tier 2: /api/browse?path=../../ normalizes path safely without server error."""
        resp = self.client.get("/api/browse?path=../../")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("current", data)

    def test_t2_12_directory_traversal_null_byte_rejected(self):
        """Tier 2: Path containing null byte '%00' returns 400 Bad Request."""
        resp = self.client.get("/api/browse?path=C:\\Windows\\System32%00secret")
        self.assertEqual(resp.status_code, 400)

    def test_t2_13_directory_traversal_nonexistent_path_404(self):
        """Tier 2: Browsing non-existent directory returns 404 Not Found."""
        resp = self.client.get("/api/browse?path=C:\\NonExistentDirectory_AssetDrop_9999")
        self.assertEqual(resp.status_code, 404)

    def test_t2_14_directory_traversal_file_as_dir_400(self):
        """Tier 2: Browsing path that points to a file returns 400 Bad Request."""
        server_py = os.path.join(PROJECT_ROOT, "server.py")
        resp = self.client.get(f"/api/browse?path={server_py}")
        self.assertEqual(resp.status_code, 400)

    def test_t2_15_directory_traversal_empty_path_defaults(self):
        """Tier 2: Empty path query parameter defaults safely without 500 error."""
        resp = self.client.get("/api/browse?path=")
        self.assertEqual(resp.status_code, 200)

    def test_t2_16_directory_traversal_root_parent_is_none(self):
        """Tier 2: Drive root browsing returns parent=None."""
        if sys.platform == "win32":
            resp = self.client.get("/api/browse?path=C:\\")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIsNone(data.get("parent"))

    # -------------------------------------------------------------------------
    # 4. Preset Pinning Boundaries
    # -------------------------------------------------------------------------
    def test_t2_17_preset_pinning_blank_name_rejected(self):
        """Tier 2: Pinning with blank name '' is rejected (400 or 422)."""
        resp = self.client.post("/api/presets/pin", json={"name": "", "path": PROJECT_ROOT})
        self.assertIn(resp.status_code, (400, 422))

    def test_t2_18_preset_pinning_whitespace_name_rejected(self):
        """Tier 2: Pinning with whitespace name '   ' is rejected (400 or 422)."""
        resp = self.client.post("/api/presets/pin", json={"name": "   ", "path": PROJECT_ROOT})
        self.assertIn(resp.status_code, (400, 422))

    def test_t2_19_preset_pinning_name_exceeds_64_chars_rejected(self):
        """Tier 2: Preset name exceeding 64 characters is rejected (400 or 422)."""
        long_name = "A" * 65
        resp = self.client.post("/api/presets/pin", json={"name": long_name, "path": PROJECT_ROOT})
        self.assertIn(resp.status_code, (400, 422))

    def test_t2_20_preset_pinning_blank_path_rejected(self):
        """Tier 2: Pinning with blank path '' is rejected (400 or 422)."""
        resp = self.client.post("/api/presets/pin", json={"name": "Valid Name", "path": ""})
        self.assertIn(resp.status_code, (400, 422))

    def test_t2_21_preset_pinning_unmounted_drive_rejected(self):
        """Tier 2: Pinning to non-existent Windows drive (e.g. Z:\\) is rejected (400)."""
        if sys.platform == "win32":
            resp = self.client.post(
                "/api/presets/pin",
                json={"name": "Ghost Drive", "path": "Z:\\Ghost\\Folder"},
            )
            self.assertEqual(resp.status_code, 400)

    # -------------------------------------------------------------------------
    # 5. UID & Password Authentication Security Boundaries
    # -------------------------------------------------------------------------
    def test_t2_22_auth_missing_token_remote_rejected_401(self):
        """Tier 2: Protected endpoint called from remote client without session token returns 401."""
        remote = TestClient(server.app, client=("192.168.1.150", 40000))
        resp = remote.post("/api/queue", json={"url": "https://youtu.be/secret"})
        self.assertEqual(resp.status_code, 401)
        self.assertIn("WWW-Authenticate", resp.headers)

    def test_t2_23_auth_wrong_password_rejected_401(self):
        """Tier 2: Login attempt with correct UID but wrong password (including non-ASCII unicode) returns 401."""
        creds = self.client.get("/api/workstation/credentials").json()
        wrong_passwords = [
            "WrongPassword999!",            # ASCII mismatch
            "wrong_case_hex",               # Lowercase candidate
            "🔑",                           # Non-ASCII emoji (tests compare_digest byte safety)
            "᚛᚛ᚑᚌᚐᚋ᚜᚜",                     # Non-ASCII unicode script (Ogham)
            "密码1234",                      # Non-ASCII CJK unicode characters
            "пароль2026",                   # Non-ASCII Cyrillic characters
            "wrong\x00password",            # Null-byte injection
            "a" * 1000,                     # Oversized password
        ]
        for bad_pw in wrong_passwords:
            resp = self.client.post(
                "/api/auth/login",
                json={"uid": creds["uid"], "password": bad_pw},
            )
            self.assertEqual(
                resp.status_code,
                401,
                f"Wrong password '{bad_pw}' yielded HTTP {resp.status_code} instead of 401",
            )
            data = resp.json()
            self.assertFalse(data.get("success", False))
            self.assertNotIn("session_token", data)

    def test_t2_24_auth_uid_format_boundaries_rejected_401(self):
        """Tier 2: Invalid UID formats (non-5-digit, letters, floats, SQLi, non-ASCII unicode) are rejected with 401."""
        creds = self.client.get("/api/workstation/credentials").json()
        pw = creds["password"]
        invalid_uids = [
            "1234",          # 4 digits
            "123456",        # 6 digits
            "ABCDE",         # letters
            "123.4",         # float
            "1e4",           # scientific notation
            "' OR '1'='1",   # SQL injection
            "<script>",      # XSS
            "",              # empty
            "🔑1234",        # non-ASCII emoji prefix
            "᚛᚛ᚑᚌᚐᚋ᚜᚜",      # non-ASCII unicode script
            "１２３４５",      # full-width unicode digits
            "用户ID",         # non-ASCII CJK unicode characters
            "1234\x00",      # null byte suffix
        ]
        for bad_uid in invalid_uids:
            resp = self.client.post(
                "/api/auth/login",
                json={"uid": bad_uid, "password": pw},
            )
            self.assertEqual(
                resp.status_code,
                401,
                f"Invalid UID '{bad_uid}' unexpectedly yielded {resp.status_code} (expected 401)",
            )
            data = resp.json()
            self.assertFalse(data.get("success", False))
            self.assertNotIn("session_token", data)

    def test_t2_25_auth_credentials_whitespace_trimmed_and_accepted(self):
        """Tier 2: Valid UID and password with surrounding whitespace are trimmed and accepted."""
        creds = self.client.get("/api/workstation/credentials").json()
        resp = self.client.post(
            "/api/auth/login",
            json={"uid": f"  {creds['uid']}  ", "password": f"  {creds['password']}  "},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["session_token"].startswith("ads_"))

    def test_t2_26_auth_malformed_and_forged_tokens_rejected_401(self):
        """Tier 2: Forged, malformed, or revoked session tokens are rejected with 401."""
        remote = TestClient(server.app, client=("192.168.1.150", 40000))

        # 1. Forged token
        resp1 = remote.post(
            "/api/queue",
            headers={"Authorization": "Bearer ads_forged_invalid_token_xyz"},
            json={"url": "https://youtu.be/test1"},
        )
        self.assertEqual(resp1.status_code, 401)

        # 2. Malformed scheme (Basic instead of Bearer)
        resp2 = remote.post(
            "/api/queue",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
            json={"url": "https://youtu.be/test2"},
        )
        self.assertEqual(resp2.status_code, 401)

        # 3. Empty Bearer header
        resp3 = remote.post(
            "/api/queue",
            headers={"Authorization": "Bearer "},
            json={"url": "https://youtu.be/test3"},
        )
        self.assertEqual(resp3.status_code, 401)

        # 4. Revoked token
        creds = self.client.get("/api/workstation/credentials").json()
        login_resp = self.client.post(
            "/api/auth/login",
            json={"uid": creds["uid"], "password": creds["password"]},
        )
        token = login_resp.json()["session_token"]
        revoke_session_token(token)

        resp4 = remote.post(
            "/api/queue",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": "https://youtu.be/test4"},
        )
        self.assertEqual(resp4.status_code, 401)

        # 5. Non-ASCII unicode token parameter (remote client)
        resp5 = remote.get(
            "/api/shared-folders?token=🔑",
        )
        self.assertEqual(resp5.status_code, 401)

    # -------------------------------------------------------------------------
    # 6. Subprocess Execution Failure Diagnostics
    # -------------------------------------------------------------------------
    def test_t2_27_cli_failure_capture_in_error_details(self):
        """Tier 2: Non-zero exit code captures clean stderr in error diagnostics."""
        mock = MockCLIInterceptor(
            assert_creationflags=False,
            simulate_failure=True,
            failure_code=1,
            failure_stderr="ERROR: [youtube] Video unavailable: Private video",
        )
        with patch_subprocess_cli(mock):
            with self.assertRaises(RuntimeError) as ctx:
                execute_download_job("job_fail_1", "https://youtu.be/fail", PROJECT_ROOT, "video")
            self.assertIn("Private video", str(ctx.exception))

    def test_t2_28_extract_error_details_filters_warnings(self):
        """Tier 2: extract_error_details filters out WARNING lines and isolates ERROR."""
        stderr = (
            "WARNING: [youtube] Skipping DASH manifest\n"
            "ERROR: [youtube] Unable to download video data: HTTP Error 403: Forbidden\n"
        )
        err = extract_error_details(stderr, "")
        self.assertIn("Forbidden", err)
        self.assertNotIn("Skipping DASH", err)

    # -------------------------------------------------------------------------
    # 7. Filename Length Truncation & Target Path Boundaries
    # -------------------------------------------------------------------------
    def test_t2_29_filename_template_truncates_title_to_80_chars(self):
        """Tier 2: yt-dlp format string enforces %(title).80s to prevent NTFS max path issues."""
        _, cmd = build_download_command("https://youtu.be/test", "D:/Assets/BRoll")
        idx = cmd.index("-o")
        template = cmd[idx + 1]
        self.assertIn(".80s", template)

    def test_t2_30_invalid_folder_key_rejected_400(self):
        """Tier 2: Ingest request with invalid preset key returns 400 Bad Request."""
        resp = self.client.post(
            "/api/queue",
            json={"url": "https://youtu.be/valid", "folder_key": "NonExistentPresetKey123"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Invalid folder_key", resp.json()["detail"])

    def test_t2_31_status_unknown_job_id_returns_404(self):
        """Tier 2: Querying non-existent job ID returns 404 Not Found."""
        resp = self.client.get("/api/status/00000000-0000-0000-0000-000000000000")
        self.assertEqual(resp.status_code, 404)

    def test_t2_32_format_type_case_insensitive_normalization(self):
        """Tier 2: Format types 'AUDIO', 'mp3', 'Mp3' normalize to 'audio'; others to 'video'."""
        for raw in ["AUDIO", "audio", "mp3", "MP3"]:
            resp = self.client.post(
                "/api/queue",
                json={"url": "https://youtu.be/fmt", "format_type": raw},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["format_type"], "audio")

        # Unknown format defaults to video
        resp_unknown = self.client.post(
            "/api/queue",
            json={"url": "https://youtu.be/fmt", "format_type": "unknown_super_hd"},
        )
        self.assertEqual(resp_unknown.status_code, 200)
        self.assertEqual(resp_unknown.json()["format_type"], "video")

    def test_t2_33_special_characters_in_url_query_parameters(self):
        """Tier 2: URLs with complex query parameters (&t=12s&list=PL123) parse safely."""
        complex_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123456789&index=1&t=42s"
        resp = self.client.post("/api/queue", json={"url": complex_url})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["platform"], "youtube")

    def test_t2_34_run_command_stealth_timeout(self):
        """Tier 2: run_command_stealth cleanly terminates timed-out process."""
        # Using a python one-liner sleep that exceeds timeout
        sleep_cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
        ret, stdout, stderr = run_command_stealth(sleep_cmd, timeout=0.2)
        self.assertEqual(ret, -1)
        self.assertIn("timed out", stderr.lower())

    def test_t2_35_custom_path_creation_and_routing(self):
        """Tier 2: custom_path parameter dynamically creates target folder and routes job."""
        custom_target = os.path.join(PROJECT_ROOT, "test_tier2_custom_destination")
        try:
            resp = self.client.post(
                "/api/queue",
                json={
                    "url": "https://youtu.be/custom_dir_test",
                    "custom_path": custom_target,
                },
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(os.path.isdir(custom_target))
            self.assertEqual(
                resp.json()["target_dir"],
                os.path.normpath(os.path.abspath(custom_target)),
            )
        finally:
            if os.path.isdir(custom_target):
                try:
                    os.rmdir(custom_target)
                except Exception:
                    pass

    # -------------------------------------------------------------------------
    # 8. Security Containment & Limit Defenses (Absorbed from Security Hardening)
    # -------------------------------------------------------------------------
    def test_t2_36_path_traversal_containment(self):
        """Tier 2: Path traversal outside designated shared folders is rejected."""
        presets = {"B-Roll": "D:/Assets/BRoll", "Social": "D:/Assets/Social"}
        safe_path = validate_path_containment("D:/Assets/BRoll/Subfolder", presets)
        self.assertTrue(safe_path.startswith(os.path.realpath("D:/Assets/BRoll")))

        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            validate_path_containment("D:/Assets/BRoll/../../Windows/System32", presets, is_local=False)
        self.assertEqual(ctx.exception.status_code, 400)

        with self.assertRaises(HTTPException) as ctx2:
            validate_path_containment("C:/Users/Administrator", presets, is_local=False)
        self.assertEqual(ctx2.exception.status_code, 400)

    def test_t2_37_filename_sanitization(self):
        """Tier 2: Filename sanitization strips directory traversal and illegal Windows characters."""
        dangerous = "../../etc/passwd\x00<test>:*?\"|file.mp4"
        clean = sanitize_filename(dangerous)
        self.assertNotIn("..", clean)
        self.assertNotIn("/", clean)
        self.assertNotIn("\\", clean)
        self.assertNotIn("\x00", clean)
        self.assertNotIn("<", clean)
        self.assertNotIn(">", clean)
        self.assertNotIn(":", clean)

    def test_t2_38_ssrf_and_domain_allowlist(self):
        """Tier 2: Validates HTTP/HTTPS scheme, blocks SSRF to private/loopback IPs, and enforces allowlist."""
        from fastapi import HTTPException

        # Private IP SSRF
        with self.assertRaises(HTTPException) as ctx1:
            validate_download_url("http://192.168.1.1/router_backup.mp4")
        self.assertEqual(ctx1.exception.status_code, 400)

        # Loopback SSRF
        with self.assertRaises(HTTPException) as ctx2:
            validate_download_url("http://127.0.0.1:8000/api/queue")
        self.assertEqual(ctx2.exception.status_code, 400)

        # Unsupported scheme
        with self.assertRaises(HTTPException) as ctx3:
            validate_download_url("file:///C:/Windows/win.ini")
        self.assertEqual(ctx3.exception.status_code, 400)

        # Non-allowlisted domain
        with self.assertRaises(HTTPException) as ctx4:
            validate_download_url("https://malicious-phishing-site.example.com/exploit.mp4")
        self.assertEqual(ctx4.exception.status_code, 400)

        # Allowlisted platforms
        self.assertEqual(
            validate_download_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )
        self.assertEqual(
            validate_download_url("https://instagram.com/reel/C123/"),
            "https://instagram.com/reel/C123/",
        )
        self.assertEqual(
            validate_download_url("https://tiktok.com/@user/video/123"),
            "https://tiktok.com/@user/video/123",
        )

    def test_t2_39_download_rate_limiting(self):
        """Tier 2: check_download_rate_limit enforces max 10 requests per minute per client."""
        client_id = "test_rate_limited_client_999"
        reset_download_rate_limit(client_id)
        try:
            for i in range(10):
                self.assertTrue(check_download_rate_limit(client_id), f"Request {i+1} should be permitted")
            # 11th request must be throttled
            self.assertFalse(check_download_rate_limit(client_id), "11th request in 60s must be throttled")
        finally:
            reset_download_rate_limit(client_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
