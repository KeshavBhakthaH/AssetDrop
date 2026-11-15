"""
tests/test_tier4_workflows.py — Tier 4: Real-World Operational Workflows Suite.

Tests 7 end-to-end user journeys defined in TEST_INFRA.md and PROJECT.md:
- Scenario 1: YouTube Video -> B-Roll folder (D:/Assets/BRoll)
- Scenario 2: YouTube Audio -> SFX folder (D:/Assets/SFX)
- Scenario 3: Instagram / TikTok Reel -> Social folder (D:/Assets/Social)
- Scenario 4: Pinterest scraping -> Target folder via gallery-dl
- Scenario 5: Drive traversal & custom folder pinning
- Scenario 6: Secured Wi-Fi ingestion with PIN authentication
- Scenario 7: Windows silent daemon startup & shutdown lifecycle

Coverage: >= 7 test cases.
Framework: Python standard library unittest + starlette.testclient.TestClient + tests.mock_cli.
"""

from __future__ import annotations

import os
import sys
import time
import unittest

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from starlette.testclient import TestClient

import server
from core.config import get_presets, load_config, save_config
from core.queue_manager import get_queue_manager
from core.subprocess_runner import execute_download_job
from tests.mock_cli import MockCLIInterceptor, patch_subprocess_cli, simulated_worker_func


class TestTier4Workflows(unittest.TestCase):
    """
    Tier 4: Real-World Operational Workflows Suite.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)
        cls.qm = get_queue_manager()

    def setUp(self):
        self.original_config = load_config()
        clean_cfg = dict(self.original_config)
        clean_cfg["access_pin"] = None
        save_config(clean_cfg)
        self.qm._worker_func = simulated_worker_func

    def tearDown(self):
        save_config(self.original_config)

    # -------------------------------------------------------------------------
    # Scenario 1: YouTube Video -> B-Roll Folder (D:/Assets/BRoll)
    # -------------------------------------------------------------------------
    def test_s01_youtube_video_to_broll_workflow(self):
        """Scenario 1: Ingest YouTube Video into B-Roll preset folder with stealth flags & MP4 merge."""
        target_dir = os.path.normpath(os.path.abspath("D:/Assets/BRoll"))
        os.makedirs(target_dir, exist_ok=True)

        mock = MockCLIInterceptor(
            assert_creationflags=True,
            custom_filename="B-Roll Drone Shot 4K [broll_01].mp4",
        )
        with patch_subprocess_cli(mock):
            # 1. User submits YouTube video URL via mobile PWA client (/api/queue)
            resp = self.client.post(
                "/api/queue",
                json={
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "folder_key": "B-Roll (General)",
                    "format_type": "video",
                },
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "queued")
            job_id = data["job_id"]
            self.assertEqual(data["platform"], "youtube")
            self.assertEqual(data["format_type"], "video")

            # 2. Worker executes stealth download command
            filename = execute_download_job(
                job_id=job_id,
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                target_dir=target_dir,
                format_type="video",
            )
            self.qm.complete_job(job_id, filename=filename)

            # 3. Verify subprocess flags and command arguments
            self.assertGreaterEqual(len(mock.invocations), 1)
            inv = mock.invocations[0]
            if sys.platform == "win32":
                self.assertEqual(inv["creationflags"], 0x08004000)
            cmd_str = " ".join(inv["cmd"])
            self.assertIn("-f bv*+ba/b", cmd_str)
            self.assertIn("--merge-output-format mp4", cmd_str)
            self.assertIn("%(title).80s [%(id)s].%(ext)s", cmd_str)

            # 4. Verify file was created in B-Roll folder and telemetry reports completed
            expected_file = os.path.join(target_dir, "B-Roll Drone Shot 4K [broll_01].mp4")
            self.assertTrue(os.path.isfile(expected_file))

            status_resp = self.client.get(f"/api/status/{job_id}")
            self.assertEqual(status_resp.status_code, 200)
            self.assertEqual(status_resp.json()["status"], "completed")

    # -------------------------------------------------------------------------
    # Scenario 2: YouTube Audio -> SFX Folder (D:/Assets/SFX)
    # -------------------------------------------------------------------------
    def test_s02_youtube_audio_to_sfx_workflow(self):
        """Scenario 2: Ingest YouTube Audio into SFX preset folder with MP3 320kbps extraction."""
        target_dir = os.path.normpath(os.path.abspath("D:/Assets/SFX"))
        os.makedirs(target_dir, exist_ok=True)

        mock = MockCLIInterceptor(
            assert_creationflags=True,
            custom_filename="Whoosh Sound Effect [sfx_02].mp3",
        )
        with patch_subprocess_cli(mock):
            # 1. User submits YouTube audio extraction request
            resp = self.client.post(
                "/api/queue",
                json={
                    "url": "https://youtu.be/sound_effect_clip",
                    "folder_key": "Sound Effects",
                    "format_type": "audio",
                },
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            job_id = data["job_id"]
            self.assertEqual(data["format_type"], "audio")

            # 2. Worker executes audio extraction
            filename = execute_download_job(
                job_id=job_id,
                url="https://youtu.be/sound_effect_clip",
                target_dir=target_dir,
                format_type="audio",
            )
            self.qm.complete_job(job_id, filename=filename)

            # 3. Verify yt-dlp audio extraction parameters
            inv = mock.invocations[0]
            cmd = inv["cmd"]
            self.assertIn("-x", cmd)
            self.assertIn("--audio-format", cmd)
            self.assertIn("mp3", cmd)
            self.assertIn("--audio-quality", cmd)
            self.assertIn("0", cmd)

            # 4. Verify MP3 placed in SFX folder
            mp3_path = os.path.join(target_dir, "Whoosh Sound Effect [sfx_02].mp3")
            self.assertTrue(os.path.isfile(mp3_path))

    # -------------------------------------------------------------------------
    # Scenario 3: Social Reel -> Social Folder (D:/Assets/Social)
    # -------------------------------------------------------------------------
    def test_s03_social_reel_to_social_workflow(self):
        """Scenario 3: Ingest Instagram / TikTok Reel into Social Edits folder in Direct Max Quality."""
        target_dir = os.path.normpath(os.path.abspath("D:/Assets/Social"))
        os.makedirs(target_dir, exist_ok=True)

        mock = MockCLIInterceptor(
            assert_creationflags=True,
            custom_filename="Trending Viral Reel [reel_03].mp4",
        )
        with patch_subprocess_cli(mock):
            # 1. User submits Instagram Reel
            resp = self.client.post(
                "/api/queue",
                json={
                    "url": "https://www.instagram.com/reel/C1234567890/",
                    "folder_key": "Social Edits",
                },
            )
            self.assertEqual(resp.status_code, 200)
            job_id = resp.json()["job_id"]
            self.assertEqual(resp.json()["platform"], "instagram")

            # 2. Worker runs yt-dlp Direct Max Quality
            filename = execute_download_job(
                job_id=job_id,
                url="https://www.instagram.com/reel/C1234567890/",
                target_dir=target_dir,
                format_type="video",
            )
            self.qm.complete_job(job_id, filename=filename)

            # 3. Verify file in Social Edits folder
            self.assertTrue(os.path.isfile(os.path.join(target_dir, "Trending Viral Reel [reel_03].mp4")))

    # -------------------------------------------------------------------------
    # Scenario 4: Pinterest Scraping -> Target Folder
    # -------------------------------------------------------------------------
    def test_s04_pinterest_moodboard_scraping_workflow(self):
        """Scenario 4: Ingest Pinterest Moodboard Image using gallery-dl into target destination."""
        target_dir = os.path.normpath(os.path.abspath("D:/Assets/BRoll"))
        os.makedirs(target_dir, exist_ok=True)

        mock = MockCLIInterceptor(
            assert_creationflags=True,
            custom_filename="Cinematic_Color_Palette_Pin.jpg",
        )
        with patch_subprocess_cli(mock):
            resp = self.client.post(
                "/api/queue",
                json={
                    "url": "https://www.pinterest.com/pin/999888777/",
                    "folder_key": "B-Roll (General)",
                },
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            job_id = data["job_id"]
            self.assertEqual(data["platform"], "pinterest")

            filename = execute_download_job(
                job_id=job_id,
                url="https://www.pinterest.com/pin/999888777/",
                target_dir=target_dir,
                format_type="video",
            )
            self.qm.complete_job(job_id, filename=filename)

            # Verify gallery-dl was invoked with --dest
            inv = mock.invocations[0]
            self.assertTrue(any("gallery-dl" in arg for arg in inv["cmd"]))
            self.assertIn("--dest", inv["cmd"])

            # Verify image file exists
            self.assertTrue(os.path.isfile(os.path.join(target_dir, "Cinematic_Color_Palette_Pin.jpg")))

    # -------------------------------------------------------------------------
    # Scenario 5: Drive Traversal & Custom Preset Pinning
    # -------------------------------------------------------------------------
    def test_s05_drive_traversal_and_preset_pinning_workflow(self):
        """Scenario 5: Discover drives -> traverse subfolder -> pin preset -> persist to config.json."""
        # 1. Enumerate drives
        drives_resp = self.client.get("/api/drives")
        self.assertEqual(drives_resp.status_code, 200)
        drives = drives_resp.json()["drives"]
        self.assertGreater(len(drives), 0)

        # 2. Browse directory
        browse_resp = self.client.get(f"/api/browse?path={PROJECT_ROOT}")
        self.assertEqual(browse_resp.status_code, 200)
        subdirs = browse_resp.json().get("subdirectories") or browse_resp.json().get("folders")
        self.assertIn("static", subdirs)

        # 3. Pin custom folder as preset
        custom_folder = os.path.join(PROJECT_ROOT, "test_tier4_pinned_nle_bin")
        os.makedirs(custom_folder, exist_ok=True)
        try:
            pin_resp = self.client.post(
                "/api/presets/pin",
                json={"name": "NLE DaVinci Bin", "path": custom_folder},
            )
            self.assertEqual(pin_resp.status_code, 200)

            # 4. Verify preset exists in config and is returned by /folders
            folders_resp = self.client.get("/folders")
            self.assertIn("NLE DaVinci Bin", folders_resp.json()["folders"])
            self.assertEqual(
                folders_resp.json()["presets"]["NLE DaVinci Bin"],
                os.path.normpath(os.path.abspath(custom_folder)),
            )
        finally:
            if os.path.isdir(custom_folder):
                try:
                    os.rmdir(custom_folder)
                except Exception:
                    pass

    # -------------------------------------------------------------------------
    # Scenario 6: Complete Mobile UID & Password Ingestion Workflow
    # -------------------------------------------------------------------------
    def test_s06_mobile_uid_password_e2e_workflow(self):
        """Scenario 6: Complete Mobile UID/Password Ingestion Workflow.
        1. PC Server starts with 5-digit UID and startup connection password.
        2. Remote mobile client attempts unauthenticated request to /api/queue -> receives 401 Unauthorized.
        3. Mobile client connects via POST /api/auth/login with UID and password -> 200 OK with ads_ token.
        4. Mobile client queries GET /api/shared-folders to populate dropdown -> receives phone-safe folders.
        5. Mobile client enqueues download via POST /api/queue with selected folder & format -> 200 (<50ms).
        6. Ingestion completes; PC queue and downloaded files history update with filename, location, and completion time.
        """
        # 1. PC Credentials
        creds = self.client.get("/api/workstation/credentials").json()
        uid = creds["uid"]
        password = creds["password"]
        self.assertEqual(len(uid), 5)
        self.assertEqual(len(password), 8)

        # 2. Remote mobile unauthenticated block
        remote = TestClient(server.app, client=("192.168.1.188", 45000))
        unauth_resp = remote.post("/api/queue", json={"url": "https://youtu.be/unauth_clip"})
        self.assertEqual(unauth_resp.status_code, 401)
        self.assertIn("WWW-Authenticate", unauth_resp.headers)

        # 3. Mobile authentication
        auth_resp = remote.post("/api/auth/login", json={"uid": uid, "password": password})
        self.assertEqual(auth_resp.status_code, 200)
        auth_data = auth_resp.json()
        self.assertTrue(auth_data.get("success"))
        token = auth_data["session_token"]
        self.assertTrue(token.startswith("ads_"))
        auth_header = {"Authorization": f"Bearer {token}"}

        # 4. Fetch folders for dropdown (phone-safe)
        folders_resp = remote.get("/api/shared-folders", headers=auth_header)
        self.assertEqual(folders_resp.status_code, 200)
        folders = folders_resp.json()["folders"]
        self.assertGreater(len(folders), 0)
        folder_name = folders[0]["name"]

        # 5. Submit download task
        queue_resp = remote.post(
            "/api/queue",
            headers=auth_header,
            json={"url": "https://youtu.be/authorized_clip", "folder_key": folder_name, "format_type": "video"},
        )
        self.assertEqual(queue_resp.status_code, 200)
        job_data = queue_resp.json()
        self.assertEqual(job_data["status"], "queued")
        job_id = job_data["job_id"]

        # 6. Verify job completion via QueueManager worker
        status_resp = self.client.get("/api/status")
        self.assertEqual(status_resp.status_code, 200)
        status_data = status_resp.json()
        completed = status_data.get("completed", []) + status_data.get("recent", [])
        completed_job = next((j for j in completed if j["id"] == job_id), None)
        self.assertIsNotNone(completed_job, f"Job {job_id} not found in completed history")
        self.assertTrue(completed_job.get("filename"), "Completed job missing filename")
        self.assertTrue(completed_job["filename"].endswith(".mp4"), "Filename should be an MP4 video")
        self.assertTrue(completed_job.get("completed_at") is not None, "Completed job missing completion timestamp")
        self.assertTrue("target_dir" in completed_job or "target_folder" in completed_job)

    # -------------------------------------------------------------------------
    # Scenario 7: Windows Silent Daemon Lifecycle
    # -------------------------------------------------------------------------
    def test_s07_windows_silent_daemon_management_workflow(self):
        """Scenario 7: Validates start_silent.vbs, stop_server.bat, and setup_firewall.bat."""
        vbs_path = os.path.join(PROJECT_ROOT, "start_silent.vbs")
        bat_stop = os.path.join(PROJECT_ROOT, "stop_server.bat")
        bat_firewall = os.path.join(PROJECT_ROOT, "setup_firewall.bat")
        guide_md = os.path.join(PROJECT_ROOT, "docs", "connection_guide.md")

        # 1. Verify all 4 management artifacts exist
        self.assertTrue(os.path.isfile(vbs_path), "start_silent.vbs is missing")
        self.assertTrue(os.path.isfile(bat_stop), "stop_server.bat is missing")
        self.assertTrue(os.path.isfile(bat_firewall), "setup_firewall.bat is missing")
        self.assertTrue(os.path.isfile(guide_md), "docs/connection_guide.md is missing")

        # 2. Verify VBS silent launch configuration
        with open(vbs_path, "r", encoding="utf-8") as f:
            vbs_code = f.read()
        self.assertIn("WScript.Shell", vbs_code)
        self.assertIn("pythonw", vbs_code.lower())
        self.assertIn("uvicorn", vbs_code.lower())
        self.assertIn("0.0.0.0", vbs_code)
        self.assertIn("8000", vbs_code)
        # Window style 0 (hidden) and wait mode False
        self.assertRegex(vbs_code, r",\s*0\s*,\s*False")

        # 3. Verify BAT process termination logic
        with open(bat_stop, "r", encoding="utf-8") as f:
            bat_code = f.read()
        self.assertIn("netstat", bat_code.lower())
        self.assertIn("8000", bat_code)
        self.assertIn("taskkill", bat_code.lower())
        self.assertIn("/f", bat_code.lower())

        # 4. Verify Firewall configuration
        with open(bat_firewall, "r", encoding="utf-8") as f:
            fw_code = f.read()
        self.assertIn("advfirewall", fw_code.lower())
        self.assertIn("localport=8000", fw_code.lower())
        self.assertIn("protocol=tcp", fw_code.lower())

    # -------------------------------------------------------------------------
    # Scenario 8: Custom Directory Browsing to Ingest Landing Workflow
    # -------------------------------------------------------------------------
    def test_s08_browse_to_custom_download_landing_workflow(self):
        """Scenario 8: Complete journey from drive browse to direct download landing in custom folder."""
        # 1. Mobile user browses project root directory
        browse_res = self.client.get(f"/api/browse?path={PROJECT_ROOT}")
        self.assertEqual(browse_res.status_code, 200)

        # 2. Selects a subfolder for one-off media landing
        landing_dir = os.path.join(PROJECT_ROOT, "test_tier4_landing_destination")
        os.makedirs(landing_dir, exist_ok=True)
        try:
            mock = MockCLIInterceptor(
                assert_creationflags=True,
                custom_filename="Custom_Landing_Asset.mp4",
            )
            with patch_subprocess_cli(mock):
                # 3. Dispatches ingestion pointing to this custom path
                resp = self.client.post(
                    "/api/queue",
                    json={
                        "url": "https://vimeo.com/765432109",
                        "custom_path": landing_dir,
                    },
                )
                self.assertEqual(resp.status_code, 200)
                job_id = resp.json()["job_id"]

                # 4. Subprocess completes
                filename = execute_download_job(
                    job_id=job_id,
                    url="https://vimeo.com/765432109",
                    target_dir=landing_dir,
                )
                self.qm.complete_job(job_id, filename=filename)

                # 5. File is verified in landing directory
                self.assertTrue(os.path.isfile(os.path.join(landing_dir, "Custom_Landing_Asset.mp4")))
        finally:
            if os.path.isdir(landing_dir):
                try:
                    os.rmdir(landing_dir)
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
