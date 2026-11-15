# AssetDrop: Cross-Device Media Ingestion Workstation

AssetDrop is a high-speed, local-first cross-device media ingestion engine built for video editors, content creators, and post-production workflows. It allows editors to queue media directly from their mobile devices (iOS / Android) onto their local Windows editing workstations over Wi-Fi without cloud uploads, complex pairing, or tedious configuration.

---

## 1. Quick Start

### Running the Server
```powershell
cd D:\AssetDrop
python server.py
```
Or run the native workstation desktop wrapper:
```powershell
python desktop_app.py
```

### Accessing the Interfaces
- **PC Browser**: Visit `http://localhost:8000` (or `http://localhost:8000/pc`).
- **Mobile Browser**: Connect your phone to the same Wi-Fi network and open `http://<PC_LAN_IP>:8000` (or `http://<PC_LAN_IP>:8000/mobile`).

The server automatically detects whether the client is a desktop or mobile browser via the `User-Agent` header and routes to the appropriate interface seamlessly.

---

## 2. Unified Simple Authentication (UID + Password)

All previous complex pairing flows (QR codes, ephemeral tokens, network mode toggles) have been replaced with a single, simple, robust authentication mechanism:

1. **Deterministic 5-digit Server UID**:
   - Derived deterministically from the PC's primary LAN IP using SHA-256 (`10000` to `99999`).
   - Remains stable as long as the PC remains on the same IP.
2. **Startup Connection Password**:
   - Auto-generated 8-character hex password (`secrets.token_hex(4)`) on server startup.
   - Displayed securely on the PC dashboard behind a "Show Credentials" / "Reveal" button.
3. **Mobile Connection**:
   - When the mobile app is opened for the first time, it presents **Stage 1 (Connection Screen)** prompting for the 5-digit UID and password.
   - Submitting the credentials hits `POST /api/auth/login`. The server verifies credentials in constant time (`secrets.compare_digest`) and issues an in-memory session token (`ads_<token>`).
   - The token is saved in the phone's `localStorage` and sent via `Authorization: Bearer <token>` on all requests.
   - Protected endpoints immediately reject unauthenticated requests with `401 Unauthorized`.

---

## 3. Dedicated Minimal Interfaces

### Minimal PC Interface (`/pc`)
The PC dashboard is stripped down to focus exclusively on monitoring and credentials:
- **Credentials Control**: A toggleable section displaying the 5-digit Server UID, masked connection password (with "Reveal" toggle), and workstation LAN URL.
- **Active Download Queue**: Live table showing currently active and queued downloads (file name, format, target folder, status).
- **Downloaded Files History**: Table showing completed downloads with file name, save destination, and completion timestamp.
- **Zero Extraneous Clutter**: QR codes, network toggles, shared folder configuration panels, and device revocation tables have been completely removed.

### Dedicated Two-Stage Mobile Interface (`/mobile`)
Designed specifically for small screens with zero clutter:
- **Stage 1: Connection Gate**:
  - Displays only when unauthenticated.
  - 5-digit numeric UID input and PC password field.
  - "⚡ Connect to PC" button.
- **Stage 2: Media Ingestion**:
  - Unlocked immediately upon successful connection.
  - **Media URL input** with a one-tap **📋 Paste** button.
  - **Format Selector**: Segmented toggle between **🎬 Video (MP4)** and **🎵 Audio (MP3)**.
  - **Save to PC Folder**: Dropdown populated from preconfigured PC folders (`B-Roll`, `SFX`, `Social Edits`, etc.).
  - **⚡ DOWNLOAD TO PC**: Primary download trigger with optimistic `<50ms` queue feedback.
  - Disconnect button to log out if desired.

---

## 4. Security & Abuse Defenses

AssetDrop maintains strict defense-in-depth protections on the local network:

| Threat Vector | Defense & Mitigation |
| :--- | :--- |
| **Unauthorized LAN Ingestion** | All download and protected endpoints require a valid in-memory session token. Unauthenticated requests are rejected with `401 Unauthorized`. |
| **Timing Attacks** | UID and password validations are executed in constant time using `secrets.compare_digest` with UTF-8 byte encoding. |
| **Filesystem Enumeration** | Remote mobile clients cannot browse the PC's drive hierarchy. Folder selections are restricted to predefined shared folders. |
| **Path Traversal Attacks** | Paths are resolved and verified with `os.path.realpath`, blocking directory traversal (`../`) and unauthorized system roots. |
| **SSRF (Server-Side Request Forgery)** | Media URLs are strictly validated: non-HTTP(S) schemes, private subnets (RFC 1918), loopback (`127.0.0.1`), and link-local ranges are blocked before any network connection is attempted. |
| **Domain Allowlist** | Only approved media domains (YouTube, Instagram, TikTok, Pinterest, Twitter/X, Vimeo) are accepted by default. |
| **Disk Exhaustion** | 1GB minimum free disk space floor required before queuing any download job; maximum 2 concurrent background download workers. |

---

## 5. Verification & Automated Test Suite

Run the full automated verification suite:

```powershell
python verify_e2e.py
```

### Coverage (102/102 Passing, Exit Code 0)
- **Tier 1 (Architecture & Features)**: 42/42 tests — Happy-path isolation, 5-digit UID derivation, PC dashboard minimal DOM contracts, two-stage mobile workflows.
- **Tier 2 (Boundaries & Security)**: 39/39 tests — Malformed inputs, command injection defenses, UID/password boundaries, SSRF defenses, path traversal containment.
- **Tier 3 (Concurrency & Combinations)**: 13/13 tests — Concurrent mobile logins, sub-50ms queue response SLA, multi-platform batches, telemetry polling under load.
- **Tier 4 (Real-World Workflows)**: 8/8 tests — End-to-end mobile login → queue media → PC queue/history update lifecycle.
