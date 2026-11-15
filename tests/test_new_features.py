"""
tests/test_new_features.py — Unit tests for:
1. Native Windows folder picker endpoint (/api/dialog/pick-folder)
2. Media inspection endpoint (/api/media/inspect)
3. Custom download folder management (add, list, delete, phone-sync)
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from starlette.testclient import TestClient
import server
from core.config import load_config, save_config, remove_preset


class TestNewFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)

    def test_pick_folder_dialog_localhost_isolation(self):
        """Remote clients are rejected with 403 Forbidden on folder picker dialog."""
        remote_client = TestClient(server.app, client=("192.168.1.50", 54321))
        resp = remote_client.post("/api/dialog/pick-folder")
        self.assertEqual(resp.status_code, 403)

    def test_media_inspect_youtube(self):
        """Inspect endpoint returns is_youtube=True, platform='youtube', and a thumbnail for YouTube links."""
        resp = self.client.post(
            "/api/media/inspect",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["platform"], "youtube")
        self.assertTrue(data["is_youtube"])
        self.assertTrue(bool(data["thumbnail"]))
        self.assertIn("http", data["thumbnail"])

    def test_media_inspect_non_youtube(self):
        """Inspect endpoint returns is_youtube=False for non-YouTube links."""
        resp = self.client.post(
            "/api/media/inspect",
            json={"url": "https://www.tiktok.com/@scout2015/video/6718335390845095173"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["is_youtube"])
        self.assertEqual(data["platform"], "tiktok")

    def test_media_inspect_invalid_url(self):
        """Inspect endpoint rejects invalid or empty URLs with 400 Bad Request."""
        resp_empty = self.client.post("/api/media/inspect", json={"url": ""})
        self.assertEqual(resp_empty.status_code, 400)

        resp_bad = self.client.post("/api/media/inspect", json={"url": "ftp://example.com/file.mp4"})
        self.assertEqual(resp_bad.status_code, 400)

    def test_custom_folder_allow_and_phone_sync_flow(self):
        """User can add any folder from PC, and phone immediately sees it in allowed folders."""
        custom_folder_name = "Test My Asset Folder"
        custom_folder_path = os.path.join(PROJECT_ROOT, "test_custom_assets_dir")

        try:
            # 1. Add folder from PC
            resp_add = self.client.post(
                "/api/shared-folders",
                json={"name": custom_folder_name, "path": custom_folder_path},
            )
            self.assertEqual(resp_add.status_code, 200)

            # 2. PC sees it in shared-folders
            resp_pc = self.client.get("/api/shared-folders")
            self.assertEqual(resp_pc.status_code, 200)
            pc_folders = [f["name"] for f in resp_pc.json().get("shared_folders", [])]
            self.assertIn(custom_folder_name, pc_folders)

            # 3. Remote phone sees it in /api/folders
            remote_client = TestClient(server.app, client=("192.168.1.105", 51234))
            # Login first to get session token
            creds = server.init_server_credentials()
            login_resp = remote_client.post(
                "/api/auth/login",
                json={"uid": creds["uid"], "password": creds["password"]},
            )
            self.assertEqual(login_resp.status_code, 200)
            token = login_resp.json()["session_token"]

            folders_resp = remote_client.get(
                "/api/folders",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(folders_resp.status_code, 200)
            phone_folder_names = [f["name"] for f in folders_resp.json().get("folders", [])]
            self.assertIn(custom_folder_name, phone_folder_names)

        finally:
            # Cleanup
            remove_preset(custom_folder_name)
            if os.path.isdir(custom_folder_path):
                try:
                    os.rmdir(custom_folder_path)
                except OSError:
                    pass

    def test_subfolder_discovery_and_download_resolution(self):
        """When user grants folder A, subfolders B and C are automatically discovered and resolvable."""
        import tempfile, shutil

        with tempfile.TemporaryDirectory() as td:
            folder_a_path = os.path.join(td, "FolderA")
            folder_b_path = os.path.join(folder_a_path, "SubfolderB")
            folder_c_path = os.path.join(folder_a_path, "SubfolderC")
            os.makedirs(folder_b_path, exist_ok=True)
            os.makedirs(folder_c_path, exist_ok=True)

            folder_a_name = "FolderA_Test"

            try:
                # 1. Allow FolderA
                resp_add = self.client.post(
                    "/api/shared-folders",
                    json={"name": folder_a_name, "path": folder_a_path},
                )
                self.assertEqual(resp_add.status_code, 200)

                # 2. Query shared folders
                resp_get = self.client.get("/api/shared-folders")
                self.assertEqual(resp_get.status_code, 200)
                folders = resp_get.json().get("shared_folders", [])
                matching = next((f for f in folders if f["name"] == folder_a_name), None)
                self.assertIsNotNone(matching)
                subs = matching.get("subfolders", [])
                self.assertIn("subfolderb", [s.lower() for s in subs])
                self.assertIn("subfolderc", [s.lower() for s in subs])

                # 3. Test resolve_destination_folder for subfolder 'FolderA_Test / SubfolderC'
                from server import IngestRequest, resolve_destination_folder, get_presets
                presets = get_presets()
                req_sub = IngestRequest(url="https://youtu.be/dummy", folder_key=f"{folder_a_name} / SubfolderC")
                resolved_c = resolve_destination_folder(req_sub, presets)
                self.assertEqual(os.path.normpath(resolved_c), os.path.normpath(folder_c_path))

                # 4. Test resolve_destination_folder for bare subfolder name 'SubfolderB'
                req_bare = IngestRequest(url="https://youtu.be/dummy", folder_key="SubfolderB")
                resolved_b = resolve_destination_folder(req_bare, presets)
                self.assertEqual(os.path.normpath(resolved_b), os.path.normpath(folder_b_path))

            finally:
                remove_preset(folder_a_name)

    def test_settings_modal_contracts_and_shutdown_security(self):
        """Task 1: Settings modal contracts in pc.html and server shutdown endpoint security."""
        pc_path = os.path.join(PROJECT_ROOT, "static", "pc.html")
        with open(pc_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Settings button & modal elements
        self.assertIn('id="btn-open-settings"', html)
        self.assertIn('id="pc-settings-modal"', html)
        self.assertIn('id="btn-close-settings"', html)
        self.assertIn('id="btn-stop-server"', html)
        self.assertIn('id="btn-copy-lan-url"', html)

        # Credentials elements preserved inside settings
        self.assertIn('id="pc-uid-display"', html)
        self.assertIn('id="pc-password-display"', html)
        self.assertIn('id="btn-toggle-credentials"', html)

        # Remote client probing shutdown must receive 403 Forbidden
        resp_remote = self.client.post(
            "/api/server/shutdown",
            headers={"X-Forwarded-For": "192.168.1.100"},
        )
        self.assertEqual(resp_remote.status_code, 403)

    def test_mobile_folder_modal_contracts_and_subfolder_creation(self):
        """Tasks 2 & 3: Mobile folder selection popup modal and subfolder creation on PC."""
        mobile_path = os.path.join(PROJECT_ROOT, "static", "mobile.html")
        with open(mobile_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Folder trigger & picker modal contracts
        self.assertIn('id="mobile-folder-trigger"', html)
        self.assertIn('id="folder-picker-modal"', html)
        self.assertIn('id="folder-search-input"', html)
        self.assertIn('id="btn-close-folder-picker"', html)
        self.assertIn('id="folder-picker-list"', html)
        self.assertIn('id="btn-confirm-folder-modal"', html)

        # Create New Folder contracts
        self.assertIn('id="btn-toggle-new-folder"', html)
        self.assertIn('id="new-folder-name-input"', html)
        self.assertIn('id="btn-confirm-create-folder"', html)

        # Preserved hidden select for legacy test assertions
        self.assertIn('id="mobile-folder-select"', html)

        # Test POST /api/folders/create
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            preset_name = "CreateFolderTestRoot"
            try:
                # Add test preset
                self.client.post("/api/shared-folders", json={"name": preset_name, "path": td})

                # 1. Validation error on empty name (400 or 422)
                r_empty = self.client.post("/api/folders/create", json={"parent": preset_name, "name": ""})
                self.assertIn(r_empty.status_code, (400, 422))

                # 2. Validation error on illegal Windows characters
                r_illegal = self.client.post("/api/folders/create", json={"parent": preset_name, "name": "bad:name*"})
                self.assertEqual(r_illegal.status_code, 400)

                # 3. Path traversal rejection
                r_traversal = self.client.post("/api/folders/create", json={"parent": preset_name, "name": "../escaped"})
                self.assertEqual(r_traversal.status_code, 400)

                # 4. Successful subfolder creation
                r_create = self.client.post(
                    "/api/folders/create",
                    json={"parent": preset_name, "name": "MobileNewSubfolder"},
                )
                self.assertEqual(r_create.status_code, 200)
                data = r_create.json()
                self.assertTrue(data.get("success"))
                self.assertEqual(data.get("name"), "MobileNewSubfolder")
                self.assertEqual(data.get("folder_key"), f"{preset_name} / MobileNewSubfolder")

                # Verify actual directory on disk
                created_disk_path = os.path.join(td, "MobileNewSubfolder")
                self.assertTrue(os.path.isdir(created_disk_path))

                # Verify nested creation inside the subfolder
                r_nested = self.client.post(
                    "/api/folders/create",
                    json={"parent": f"{preset_name} / MobileNewSubfolder", "name": "NestedChild"},
                )
                self.assertEqual(r_nested.status_code, 200)
                nested_disk_path = os.path.join(created_disk_path, "NestedChild")
                self.assertTrue(os.path.isdir(nested_disk_path))

            finally:
                remove_preset(preset_name)

    def test_server_password_persistence_and_deleted_preset_permanence(self):
        """Task 1: Server connection password persists in config.json and deleted presets do not reappear."""
        cfg_before = load_config()
        self.assertIn("connection_password", cfg_before)
        initial_pw = cfg_before["connection_password"]

        # Call init_server_credentials without force_refresh
        creds = server.init_server_credentials(force_refresh=False)
        self.assertEqual(creds["password"], initial_pw)

        # Verify config load again
        cfg_after = load_config()
        self.assertEqual(cfg_after.get("connection_password"), initial_pw)

        # Test deleted preset permanence
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            dummy_label = "TemporaryDeleteTestPreset"
            server.add_preset(dummy_label, td)
            cfg_added = load_config()
            self.assertIn(dummy_label, cfg_added.get("presets", {}))

            # Remove it
            removed = server.remove_preset(dummy_label)
            self.assertTrue(removed)

            # Re-read config: must not reappear
            cfg_reloaded = load_config()
            self.assertNotIn(dummy_label, cfg_reloaded.get("presets", {}))

    def test_mobile_hierarchical_explorer_and_autologin_contracts(self):
        """Task 1 & 2: Mobile explorer DOM elements, breadcrumbs, banner, and auto-login script logic."""
        mobile_path = os.path.join(PROJECT_ROOT, "static", "mobile.html")
        with open(mobile_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Explorer banner, current title, and choose current button
        self.assertIn('id="explorer-banner"', html)
        self.assertIn('id="explorer-current-title"', html)
        self.assertIn('id="btn-choose-current-folder"', html)

        # Breadcrumbs bar and Up button
        self.assertIn('id="explorer-breadcrumbs-bar"', html)
        self.assertIn('id="explorer-breadcrumbs"', html)
        self.assertIn('id="btn-nav-up"', html)

        # Action toolbar: sort and new folder
        self.assertIn('id="btn-toggle-sort"', html)
        self.assertIn('id="btn-sort-toggle-text"', html)
        self.assertIn('id="btn-toggle-new-folder"', html)

        # Inspect static/mobile.js logic
        js_path = os.path.join(PROJECT_ROOT, "static", "mobile.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js_code = f.read()

        self.assertIn("PW_STORAGE_KEY", js_code)
        self.assertIn("buildFolderTree", js_code)
        self.assertIn("renderFolderPickerList", js_code)
        self.assertIn("getCachedCredentials", js_code)
        self.assertIn("btnChooseCurrentFolder", js_code)
        self.assertIn("btnNavUp", js_code)
        self.assertIn("btnToggleSort", js_code)

    def test_deep_folder_hierarchy_traversal_beyond_3_levels(self):
        """Verify folder hierarchy traverses beyond 3 levels (up to 10 levels deep)."""
        import tempfile
        from core.traversal import scan_subfolders

        with tempfile.TemporaryDirectory() as td:
            deep_path = os.path.join(td, "Level1", "Level2", "Level3", "Level4", "Level5", "Level6")
            os.makedirs(deep_path, exist_ok=True)

            subs = scan_subfolders(td)
            self.assertIn("Level1", subs)
            self.assertIn("Level1/Level2", subs)
            self.assertIn("Level1/Level2/Level3", subs)
            self.assertIn("Level1/Level2/Level3/Level4", subs)
            self.assertIn("Level1/Level2/Level3/Level4/Level5", subs)
            self.assertIn("Level1/Level2/Level3/Level4/Level5/Level6", subs)


if __name__ == "__main__":
    unittest.main()
