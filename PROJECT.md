# Project: AssetDrop — Cross-Device Media Ingestion Engine (v3.0 Redesign)

## Architecture

AssetDrop is a high-performance cross-device media ingestion system running on Windows, featuring complete separation between PC Workstation Host and Mobile Client interfaces, an explicit connection gate on mobile, and a terminal-modern SaaS aesthetic.

```
+─────────────────────────────────────────────────────────────────────────────────────────────+
│                                  Client & Presentation Layer                                │
├──────────────────────────────────────────────────────────┬──────────────────────────────────┤
│           PC Workstation Dashboard (/pc, /)              │     Mobile Client (/mobile, /)   │
│  - Dark-minimal SaaS aesthetic (#09090b)                 │  - Gate 1: Connection Screen     │
│  - Strictly OMITS link paste box                         │    * 'Connect to your PC' prompt │
│  - Shared Folders Manager (Add, Remove, Open in Explorer)│    * QR scan & manual IP/Pass    │
│  - Transfers & Ingestion Dashboard (Live feed, status,   │    * localStorage token persist  │
│    thumbnail/icon, format, Open in Folder)               │  - Gate 2: Clean Download UI     │
│  - Workstation Connection & Security Card (Live QR code, │    * '● Connected to [PC Name]'  │
│    LAN IP 192.168.220.36:8000, password reveal toggle,   │    * Clean link input + [ Paste ]│
│    paired devices registry with one-click Revoke)        │    * MP4 (Video) / MP3 (Audio)   │
│  - Served to desktop browsers & PyWebView desktop_app.py │    * PC Shared Folders dropdown  │
│                                                          │    * [ ⬇ Download to PC ] action │
│                                                          │    * Instant toast (<50ms)       │
│                                                          │    * NO 'Media Ingestion Engine' │
│                                                          │    * NO 'Workstation Hub' tab    │
│                                                          │    * NO preset category labels   │
└──────────────────────────────────────────────────────────┴──────────────────────────────────┘
                                             │
                                             ▼ HTTP / JSON
+─────────────────────────────────────────────────────────────────────────────────────────────+
│                               FastAPI Backend Server (Port 8000)                            │
│  - Dynamic User-Agent & Route Dispatcher (GET /, GET /pc, GET /mobile)                      │
│  - Ingestion Queue (POST /api/queue, /download) [< 50ms SLA via Background ThreadPool]      │
│  - Transfers Telemetry & Explorer Trigger (GET /api/transfers, POST /api/transfers/{id}/open)│
│  - Shared Folders Manager (GET, POST, DELETE /api/shared-folders, POST .../open)            │
│  - Workstation Pairing & Device Registry (POST /api/pair, GET /api/devices, Revoke)        │
│  - Security Middleware: secrets.compare_digest constant-time auth & token validation         │
│  - Windows Drive & Subfolder Traversal (GET /api/drives, GET /api/browse)                   │
+─────────────────────────────────────────────────────────────────────────────────────────────+
                                             │
                                             ▼
+─────────────────────────────────────────────────────────────────────────────────────────────+
│                             Subprocess Execution Engine                                     │
│  - Windows Flags: CREATE_NO_WINDOW | 0x00004000 (0x08004000) [Below Normal Priority]        │
│  - Resilient CLI Path Resolver (shutil.which -> Python Scripts -> -m module)                 │
│  - Platform Routing Matrix: yt-dlp, gallery-dl, ffmpeg, ffprobe                             │
│  - Output Template: %(title).80s [%(id)s].%(ext)s                                           │
+─────────────────────────────────────────────────────────────────────────────────────────────+
                                             │
                                             ▼
+─────────────────────────────────────────────────────────────────────────────────────────────+
│                             Windows Desktop & Filesystem Integration                        │
│  - Native Desktop Window: PyWebView 6.2.1 loading PC Dashboard                              │
│  - Windows System Tray: pystray 0.19.5 with minimize-to-tray & background persistence       │
│  - File Explorer Integrations: os.startfile() and explorer.exe /select,"<filepath>"         │
│  - Target Directories: D:/Assets, D:/Projects, and custom user-defined shared folders       │
+─────────────────────────────────────────────────────────────────────────────────────────────+
```

---

## Feature Inventory

Every feature from the Redesign Specification and Survey Phase is cataloged below with its assigned milestone.

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Shared Folders Deletion API | `DELETE /api/presets/{name}` & `DELETE /api/shared-folders/{name}` removing folder from config | M1-R | ORIGINAL_REQUEST §R1 |
| 2 | Canonical Shared Folders API | `GET /api/shared-folders` & `POST /api/shared-folders` with folder metadata and auto-creation | M1-R | ORIGINAL_REQUEST §R1 |
| 3 | Shared Folder Explorer Launch | `POST /api/shared-folders/open` and enhanced `POST /api/open-folder` opening directory in Explorer | M1-R | ORIGINAL_REQUEST §R1 |
| 4 | Canonical Device Pairing API | `POST /api/pair` and `/api/auth/pair` pairing via UID & password with `adt_<token>` generation | M1-R | ORIGINAL_REQUEST §R3 |
| 5 | Device Revocation API | `DELETE /api/devices/{device_uid}` and `POST /api/devices/revoke` immediately purging device token | M1-R | ORIGINAL_REQUEST §R3 |
| 6 | Transfers Telemetry Feed API | `GET /api/transfers` returning active/completed jobs with title, size, formatted string, format, icon | M1-R | ORIGINAL_REQUEST §R1 |
| 7 | Transfer File Explorer Highlight | `POST /api/transfers/{job_id}/open` executing `explorer.exe /select,"<filepath>"` to highlight file | M1-R | ORIGINAL_REQUEST §R1 |
| 8 | Workstation Settings API | `GET /api/workstation/settings` (localhost-restricted) returning password for PC reveal toggle | M1-R | ORIGINAL_REQUEST §R1 |
| 9 | Immediate Revocation Invalidation | `require_pin_auth` immediately returning 401 Unauthorized for revoked device tokens | M1-R | ORIGINAL_REQUEST §R3 |
| 10 | Dependencies Declaration | Adding `qrcode`, `pystray`, `pywebview`, and `pillow` to `requirements.txt` | M1-R | ORIGINAL_REQUEST §R4 |
| 11 | Smart User-Agent Routing | `server.py` routing `/` to `pc.html` for desktop/WebView2 and `mobile.html` for mobile UAs | M2-R | ORIGINAL_REQUEST §R1, R2 |
| 12 | Explicit Route Endpoints | Canonical `GET /pc` and `GET /mobile` endpoints serving respective interfaces | M2-R | ORIGINAL_REQUEST §R1, R2 |
| 13 | PC Interface Paste Box Omission | `static/pc.html` strictly omits URL link paste input, paste button, and download trigger | M2-R | ORIGINAL_REQUEST §R1 |
| 14 | PC Shared Folders Manager UI | Responsive card to view shared folders, add new folder, delete folder, and open in Explorer | M2-R | ORIGINAL_REQUEST §R1 |
| 15 | PC Transfers Dashboard UI | Real-time table showing active/completed downloads, title, icon, MP4/MP3, size, status, open button | M2-R | ORIGINAL_REQUEST §R1 |
| 16 | PC Workstation Connection Card | Display live pairing QR code, LAN IP `192.168.220.36:8000`, password reveal toggle, paired devices table | M2-R | ORIGINAL_REQUEST §R1 |
| 17 | PC One-Click Revoke Action | One-click button in paired devices table to immediately revoke mobile access | M2-R | ORIGINAL_REQUEST §R1, R3 |
| 18 | Desktop App WebView2 Loading | `desktop_app.py` loads PC Dashboard via `http://127.0.0.1:8000/` with PyWebView | M2-R | ORIGINAL_REQUEST §R4 |
| 19 | Desktop App System Tray Actions | Maintain Windows tray icon (`pystray`), minimize-to-tray on close, and context menu | M2-R | ORIGINAL_REQUEST §R4 |
| 20 | Mobile Gate 1 Connection Screen | 'Connect to your PC' prompt, QR scan option, manual IP & password entry for unpaired clients | M3-R | ORIGINAL_REQUEST §R2 |
| 21 | Mobile Token Persistence & Bypass | Secure storage of token in `localStorage`, automatic bypass of Gate 1 on subsequent visits | M3-R | ORIGINAL_REQUEST §R2 |
| 22 | Mobile Gate 2 Top Bar | Header displaying `● Connected to [PC Name]` with live green status indicator | M3-R | ORIGINAL_REQUEST §R2 |
| 23 | Mobile One-Tap Paste Button | Clean input with one-tap `[ Paste ]` button supporting `navigator.clipboard.readText()` & fallbacks | M3-R | ORIGINAL_REQUEST §R2 |
| 24 | Mobile Two-Button Format Toggle | High-contrast toggle: `🎬 MP4 (Video)` vs `🎵 MP3 (Audio)` | M3-R | ORIGINAL_REQUEST §R2 |
| 25 | Mobile Dynamic Destination Dropdown | Dropdown selector dynamically populated from PC shared folders | M3-R | ORIGINAL_REQUEST §R2 |
| 26 | Mobile Instant Toast Feedback | `[ ⬇ Download to PC ]` action providing optimistic <50ms toast feedback and queueing | M3-R | ORIGINAL_REQUEST §R2 |
| 27 | Mobile Clutter Cleanup | Complete removal of 'Media Ingestion Engine' text, 'Workstation Hub' tab, and preset chips | M3-R | ORIGINAL_REQUEST §R2 |
| 28 | Capacitor Android Sync | Update `mobile/build.js` to sync `mobile.html` as `mobile/www/index.html` for Android build | M3-R | ORIGINAL_REQUEST §R2 |
| 29 | Tier 1 Verification Updates | Add test cases for PC route without paste box, mobile route, shared folders CRUD, workstation info | M4-R | ORIGINAL_REQUEST §R5 |
| 30 | Tier 2 Verification Updates | Add test cases for wrong password 401, revoked token 401, invalid folder paths | M4-R | ORIGINAL_REQUEST §R5 |
| 31 | Tier 3 Verification Updates | Add test cases for multi-device concurrent pairing and selective revocation | M4-R | ORIGINAL_REQUEST §R5 |
| 32 | Tier 4 Verification Updates | Add test case for full E2E workflow (pair -> dropdown -> queue -> PC transfer -> explorer open) | M4-R | ORIGINAL_REQUEST §R5 |
| 33 | Verification Runner Pass | `verify_e2e.py` executes and passes 100% of all tiers | M4-R / M5-R | ORIGINAL_REQUEST §R5 |
| 34 | Final Acceptance & Adversarial Hardening | White-box adversarial testing, edge case stress tests, and repository-wide forensic audit | M5-R | Integrity Forensics |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1-R | Backend Security, Pairing & Shared Folders APIs | `core/config.py`, `core/queue_manager.py`, `server.py` (API endpoints: `/api/pair`, `/api/devices`, `/api/devices/revoke`, `/api/shared-folders`, `/api/transfers`, `/api/workstation/settings`, `requirements.txt`) | none | PLANNED |
| M2-R | PC Workstation Dashboard & Desktop App Window | `server.py` (routing: `/`, `/pc`, `/mobile`), `static/pc.html`, `static/pc.js`, `static/pc.css`, `desktop_app.py` | M1-R | PLANNED |
| M3-R | Mobile Interface & Connection Gate | `static/mobile.html`, `static/mobile.js`, `static/mobile.css`, `mobile/build.js`, `static/sw.js` | M1-R | PLANNED |
| M4-R | Automated Verification Suite Updates | `tests/test_tier1_features.py`, `tests/test_tier2_boundaries.py`, `tests/test_tier3_combinations.py`, `tests/test_tier4_workflows.py`, `verify_e2e.py` | M1-R, M2-R, M3-R | PLANNED |
| M5-R | Final E2E Test Pass & Adversarial Hardening | 100% pass of `verify_e2e.py`, Tier 5 adversarial stress testing, repository-wide forensic integrity audit | M1-R, M2-R, M3-R, M4-R | PLANNED |

---

## Interface Contracts

### Module: `core/config.py`
- `remove_preset(name: str) -> bool`: Unshares a preset folder from `config.json`. Returns `True` if found and removed.
- `pair_device(device_uid: str, device_name: str, password_candidate: str, client_ip: str) -> dict`: Validates password using `secrets.compare_digest`. Generates `adt_<token>`, records device, persists config.
- `verify_device_token(token_candidate: str) -> Optional[dict]`: Constant-time token lookup. Returns device info or `None`.
- `revoke_device(device_uid: str) -> bool`: Immediately removes device from registry and persists config.

### Module: `core/queue_manager.py`
- `Job.to_dict()`: Returns dictionary including `id`, `url`, `platform`, `format_type`, `title`, `filename`, `file_size_bytes`, `file_size_str`, `status`, `target_dir`, `created_at`, `completed_at`.

### Module: `server.py` Endpoints
- `GET /`: Evaluates User-Agent. Serves `static/pc.html` for desktop/WebView2 and `static/mobile.html` for mobile devices.
- `GET /pc`: Explicitly serves `static/pc.html`.
- `GET /mobile`: Explicitly serves `static/mobile.html`.
- `POST /api/pair`: Body `{device_uid, device_name, password}` -> `{success: true, token, workstation_id}` or `401`.
- `GET /api/devices`: Returns array of paired devices `{device_uid, device_name, paired_at, last_seen, ip}`.
- `DELETE /api/devices/{device_uid}` and `POST /api/devices/revoke`: Revokes device access. Returns 200 or 404.
- `GET /api/shared-folders`: Returns `{folders: [{name, path, exists, is_default}], presets: {...}}`.
- `POST /api/shared-folders`: Body `{name, path}` -> creates folder, adds to presets.
- `DELETE /api/shared-folders/{name}`: Removes folder from presets.
- `POST /api/shared-folders/open`: Launches Windows Explorer for folder.
- `GET /api/transfers`: Returns snapshot of active and completed transfers with title, size, status, format.
- `POST /api/transfers/{job_id}/open`: Highlights downloaded file in Windows Explorer (`explorer.exe /select,...`).
- `GET /api/workstation/settings`: Localhost-restricted endpoint returning `{password, workstation_id, local_ip}` for PC reveal toggle.

---

## Code Layout

```
D:\AssetDrop\
├── config.json                     # Configuration, presets, authorized devices
├── server.py                       # FastAPI application & route dispatcher
├── desktop_app.py                  # PyWebView desktop window & pystray integration
├── requirements.txt                # Python package dependencies
├── core/
│   ├── __init__.py
│   ├── config.py                   # Presets, device pairing, constant-time auth
│   ├── routing.py                  # Platform routing & tool resolution
│   ├── subprocess_runner.py        # Windows CREATE_NO_WINDOW | 0x4000 execution
│   ├── queue_manager.py            # Ingestion queue & transfers telemetry
│   └── traversal.py                # Drive and folder traversal
├── static/
│   ├── pc.html                     # PC Workstation Dashboard (no paste box)
│   ├── pc.js                       # PC Dashboard logic (folders, transfers, security)
│   ├── pc.css                      # PC Dashboard dark-minimal SaaS styling
│   ├── mobile.html                 # Mobile Client (Gate 1 + Gate 2)
│   ├── mobile.js                   # Mobile Client logic (pairing, paste, format, download)
│   ├── mobile.css                  # Mobile touch ergonomics & terminal-modern styling
│   ├── index.html                  # Legacy/Router fallback
│   ├── style.css                   # Preserved core styles
│   ├── app.js                      # Preserved router
│   ├── manifest.json               # Mobile PWA manifest
│   ├── sw.js                       # Service worker
│   └── icons/                      # Favicons and PWA icons
├── mobile/
│   ├── build.js                    # Capacitor build sync script
│   ├── capacitor.config.json       # Mobile app configuration
│   └── www/                        # Synced web assets
├── tests/
│   ├── test_tier1_features.py      # Tier 1: Feature isolation
│   ├── test_tier2_boundaries.py    # Tier 2: Boundary & security edge cases
│   ├── test_tier3_combinations.py  # Tier 3: Concurrency & cross-feature tests
│   └── test_tier4_workflows.py     # Tier 4: Real-world end-to-end workflows
├── verify_e2e.py                   # Automated 4-tier verification runner
├── TEST_INFRA.md                   # Test infrastructure blueprint
└── TEST_READY.md                   # Test suite readiness attestation
```
