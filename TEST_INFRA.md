# E2E Test Infra: AssetDrop (v2.0)

## Test Philosophy
- **Requirement-Driven & Opaque-Box**: Tests are derived directly from `ORIGINAL_REQUEST.md` and `AssetDrop Technical and Product Brief.pdf` (Version 2.0). They treat the application from an end-user / HTTP client / Windows OS consumer perspective without relying on internal module private methods.
- **Zero-Dependency Test Runner**: Uses Python's built-in `unittest` and `starlette.testclient.TestClient` / `httpx`. Does not require external packages like `pytest` which are absent from the environment.
- **Methodology**: Systematic 4-tier testing combining Category-Partition, Boundary Value Analysis (BVA), Pairwise Combinatorial Testing, and Realistic Workload Scenarios.
- **Dual-Mode Execution**: Built-in mock CLI simulation engine (`tests/mock_cli.py`) for rapid, deterministic, reproducible offline testing, with an optional `--live` flag for real network media ingestion when desired.

---

## Feature Inventory & Test Mapping

| # | Feature | Source (Requirement) | Tier 1 (Features) | Tier 2 (Boundaries) | Tier 3 (Combinations) | Tier 4 (Workflows) |
|---|---------|----------------------|:-----------------:|:-------------------:|:---------------------:|:------------------:|
| 1 | Config & Preset Auto-Creation | R3 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 2 | Resilient CLI Tool Resolution | R1, R2, Survey | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 3 | Subprocess Stealth Flags (0x08004000) | R2 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 4 | Platform Matrix: YouTube Video | R1 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 5 | Platform Matrix: YouTube Audio | R1 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 6 | Platform Matrix: Instagram / TikTok | R1 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 7 | Platform Matrix: Pinterest (gallery-dl) | R1 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 8 | Platform Matrix: Twitter / X / Others | R1 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 9 | Filename Template `%(title).80s [%(id)s]` | R1 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 10 | Background Ingestion Queue & SLA (<50ms) | R1, R6 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 11 | Ingestion API (`/api/queue`, `/download`) | R1 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 12 | Status & Telemetry API (`/api/status`) | R1 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 13 | Preset Query & Pinning API | R3 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 14 | Drive Enumeration API (`/api/drives`) | R1, R3 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 15 | Live Traversal API (`/api/browse`) | R1, R3 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 16 | PIN Authentication & Security | R3 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 17 | Obsidian Dark Theme UI (`#090d16`) | R4 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 18 | Mobile Touch Targets (>=44px) | R4 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 19 | Sub-50ms Instant Queue Toast | R4 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 20 | Dynamic Format Toggle vs Badge | R4 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 21 | Rapid Clipboard Paste & Fallback | R4 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 22 | Sliding Bottom Sheet PC Browser | R3, R4 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 23 | Expandable Status Tray & Diagnostics | R4 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 24 | PWA Manifest & Service Worker | R4 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 25 | Windows Silent Boot (`start_silent.vbs`) | R5 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 26 | Process Shutdown (`stop_server.bat`) | R5 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 27 | Firewall Automation (`setup_firewall.bat`) | R5 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |
| 28 | Network Connection Guide | R5 | ✓ (5 cases) | ✓ (5 cases) | ✓ | ✓ |

---

## Test Architecture
- **Location**: `tests/` and root `verify_e2e.py`.
- **Runner Invocation**: `python verify_e2e.py` or `python -m unittest discover tests`.
- **Exit Code Semantics**:
  - `0`: All test cases across all active tiers pass cleanly.
  - Non-zero: One or more assertions failed or encountered an error.

### Structure:
- `tests/mock_cli.py`: Mock subprocess interceptor that validates CLI arguments, creationflags, and simulates media output generation.
- `tests/test_tier1_features.py`: Tests each feature in isolation (happy-path).
- `tests/test_tier2_boundaries.py`: Tests edge cases, boundary values, malformed inputs, traversal escapes, command injections.
- `tests/test_tier3_combinations.py`: Pairwise interactions, parallel ingestion bursts (10 concurrent requests < 50ms), status polling under load.
- `tests/test_tier4_workflows.py`: Complete user journeys (from mobile submission to file arrival, status tray sync, Windows headless management).

---

## Real-World Application Scenarios (Tier 4)

| # | Scenario | Features Exercised | Expected Outcome |
|---|----------|--------------------|------------------|
| 1 | B-Roll Ingestion from YouTube Video | F1, F3, F4, F9, F10, F11, F12 | Ingests MP4 video into `D:/Assets/BRoll` with proper naming and status tray completion |
| 2 | Sound Effects Extraction from YouTube Audio | F1, F3, F5, F9, F10, F11, F12 | Ingests MP3 320k into `D:/Assets/SFX` without video stream |
| 3 | Social Reel Ingestion from Instagram / TikTok | F1, F3, F6, F9, F10, F11, F12 | Ingests MP4 into `D:/Assets/Social` preserving high framerate |
| 4 | Pinterest Moodboard Reference Scraping | F1, F3, F7, F10, F11, F12 | Uses `gallery-dl` to download high-res images into target directory |
| 5 | Custom Drive Traversal & Preset Pinning | F13, F14, F15 | Traverses `C:\` or `D:\` subfolders, pins a new directory, persists to `config.json` |
| 6 | Secured Wi-Fi Ingestion with PIN Authentication | F16, F11, F12 | Blocks unauthenticated request (401), admits request with `X-Access-PIN`, completes download |
| 7 | Windows Silent Daemon Lifecycle | F25, F26, F27 | Starts headless via VBS, verifies port 8000 listening, terminates cleanly via BAT |

---

## Coverage Thresholds
- **Tier 1 (Feature Coverage)**: >= 28 test cases (covering all 28 features).
- **Tier 2 (Boundary & Corner Cases)**: >= 28 test cases.
- **Tier 3 (Cross-Feature Combinations)**: >= 10 test cases.
- **Tier 4 (Real-World Workflows)**: >= 7 test cases.
- **Total Test Suite**: >= 73 automated test cases executed via `verify_e2e.py`.
