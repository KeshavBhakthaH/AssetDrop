# AssetDrop — Cross-Device Media Ingestion Engine (v2.0)
## Complete Network Connection & Mobile Setup Guide

---

## 1. Overview & Architecture

**AssetDrop** is a high-performance, headless media ingestion daemon designed to run stealthily on your primary video editing workstation (Windows 11 / 10). It allows you to discover, bookmark, and download high-resolution media (YouTube, Instagram, TikTok, Pinterest, Twitter/X) directly from your mobile phone into your DaVinci Resolve or Adobe Premiere Pro asset bins with zero UI popups, zero terminal window flashes, and zero dropped frames.

```
       +-----------------------+              +-----------------------+
       |   iPhone / iPad iOS   |              |  Android Smartphone   |
       |  Safari PWA on Wi-Fi  |              |  Chrome PWA on 4G/5G  |
       +-----------+-----------+              +-----------+-----------+
                   |                                      |
                   | Local Wi-Fi (192.168.x.x)            | Tailscale WireGuard (100.x.y.z)
                   +------------------+-------------------+
                                      |
                                      ▼
             +--------------------------------------------------+
             |            Windows Workstation Host              |
             |  FastAPI / Uvicorn Server (Port 8000)            |
             |  ----------------------------------------------  |
             |  - start_silent.vbs (Headless Launch)            |
             |  - setup_firewall.bat (Port 8000 Inbound Rule)   |
             |  - stop_server.bat (Safe Process Killer)         |
             +------------------------+-------------------------+
                                      |
                     CREATE_NO_WINDOW | 0x00004000 (Low Priority)
                                      ▼
             +--------------------------------------------------+
             |         NLE Storage / Preset Directories         |
             |  D:/Assets/BRoll   |  D:/Assets/Social           |
             |  D:/Assets/SFX     |  D:/Assets/Music            |
             +--------------------------------------------------+
```

---

## 2. Local Wi-Fi LAN Setup

Connecting over your local Wi-Fi network provides the fastest, lowest-latency ingestion experience (<50ms queue response).

### Step 1: Identify Host Workstation IPv4 Address
1. Open PowerShell or Command Prompt on the Windows host.
2. Run:
   ```cmd
   ipconfig
   ```
3. Locate your active network adapter (e.g., `Wireless LAN adapter Wi-Fi` or `Ethernet adapter`).
4. Note the **IPv4 Address**. On this workstation, the current Wi-Fi address is:
   ```
   192.168.220.36
   ```
   *(Your IP may vary depending on DHCP lease: e.g., `192.168.1.150` or `10.0.0.42`)*.

### Step 2: Open Windows Defender Firewall for Port 8000
By default, Windows Defender Firewall blocks unsolicited incoming connections from other devices on the LAN.

1. In the `D:\AssetDrop` folder, right-click `setup_firewall.bat` and select **Run as administrator** (or double-click it and accept the UAC prompt).
2. The script executes:
   ```cmd
   netsh advfirewall firewall add rule name="AssetDrop Ingestion Server (Port 8000)" dir=in action=allow protocol=TCP localport=8000 profile=any
   ```
3. You will see:
   ```
   [AssetDrop] SUCCESS: Inbound rule for Port 8000 added to Windows Defender Firewall.
   ```

### Step 3: Start the Server Headlessly
Double-click `start_silent.vbs`. 
- The server will boot in the background via `pythonw.exe`.
- No black console windows or command prompts will appear.
- The server will bind to `0.0.0.0:8000`, listening on all network interfaces.

### Step 4: Access from Mobile Browser
1. Connect your mobile phone (iPhone or Android) to the **same Wi-Fi network** as the workstation.
2. Open your mobile browser (Safari on iOS, Chrome on Android).
3. Navigate to:
   ```
   http://192.168.220.36:8000
   ```
   *(Replace with your workstation's actual IPv4 if different)*.
4. The dark obsidian AssetDrop interface (`#090d16`) will appear immediately.

> **Wi-Fi Router Notice**: Ensure your router does not have **AP Isolation** or **Guest Network Isolation** enabled, as this blocks client-to-client communication within the same subnet.

---

## 3. Remote 4G / 5G Cellular Access via Tailscale

Tailscale creates a secure, encrypted peer-to-peer mesh network (built on WireGuard) enabling you to drop assets from your phone into your workstation from anywhere in the world over cellular data (4G/5G/LTE), coffee shop Wi-Fi, or remote locations, with **zero port forwarding** and **zero router reconfiguration**.

### Step 1: Install Tailscale on Windows Workstation
1. Download and install Tailscale for Windows from [https://tailscale.com/download/windows](https://tailscale.com/download/windows).
2. Launch Tailscale from the Windows system tray and log in with your account (Google, Apple, Microsoft, or GitHub).
3. Open PowerShell and obtain your machine's 100.x.y.z Tailscale IP address:
   ```cmd
   tailscale ip -4
   ```
   Example output: `100.85.120.40`.

### Step 2: Install Tailscale on Mobile Phone
1. Install **Tailscale** from the App Store (iOS) or Google Play Store (Android).
2. Log in using the **exact same account** used on the Windows workstation.
3. Toggle the VPN switch to **Connected** in the Tailscale app.

### Step 3: Access AssetDrop Anywhere over 4G/5G
1. Turn off Wi-Fi on your phone to test cellular data (4G/5G).
2. Open mobile Safari or Chrome and navigate to:
   ```
   http://100.x.y.z:8000
   ```
   *(Replace `100.x.y.z` with your workstation's Tailscale IP, e.g., `http://100.85.120.40:8000`)*.
3. You now have end-to-end encrypted remote media ingestion directly to your PC timeline.

---

## 4. Mobile PWA Installation (Home Screen Experience)

AssetDrop is engineered as a standalone Progressive Web Application (PWA) with touch targets >= 44px, vibration feedback, and fullscreen operation.

### iOS (iPhone / iPad — Safari)
1. Navigate to your AssetDrop URL (`http://192.168.220.36:8000` or `http://100.x.y.z:8000`) in **Safari**.
2. Tap the **Share** button (the square with an arrow pointing upward at the bottom of the screen).
3. Scroll down in the share sheet and tap **Add to Home Screen**.
4. Tap **Add** in the top right corner.
5. The **AssetDrop** icon will appear on your iOS home screen.
6. Launching from the home screen runs AssetDrop in borderless fullscreen standalone mode without Safari browser toolbars.

### Android (Chrome / Firefox / Brave)
1. Open Chrome and navigate to the AssetDrop URL.
2. A prompt banner may appear at the bottom: **"Add AssetDrop to Home screen"**. Tap it.
3. If not shown automatically, tap the **three-dot menu (⋮)** in the upper right.
4. Select **"Install app"** or **"Add to Home screen"**.
5. Tap **Install**.
6. The app is installed into your Android app drawer and home screen as a native-like PWA.

---

## 5. Security & Access PIN Configuration

AssetDrop operates in one of two security modes configured in `D:\AssetDrop\config.json`.

### Mode A: Open Access Mode (Default)
When `"access_pin": null` or `""` in `config.json`:
- Full access is granted to any device reachable on your local Wi-Fi or authenticated Tailscale mesh.
- No PIN prompts or logins required.
- Recommended for private personal networks and solo creators.

### Mode B: PIN Protected Mode
If sharing a local Wi-Fi network (office, studio, co-working space), you can protect AssetDrop with a secure PIN:

1. Open `D:\AssetDrop\config.json` in an editor.
2. Set your custom PIN:
   ```json
   {
     "host": "0.0.0.0",
     "port": 8000,
     "access_pin": "8421",
     "presets": {
       "B-Roll (General)": "D:/Assets/BRoll",
       "Social Edits": "D:/Assets/Social",
       "Sound Effects": "D:/Assets/SFX",
       "Background Music": "D:/Assets/Music"
     }
   }
   ```
3. Restart the server (`stop_server.bat` followed by `start_silent.vbs`).
4. Any device accessing the REST API must provide the PIN via:
   - Request Header: `X-Access-PIN: 8421`
   - URL Query Parameter: `http://192.168.220.36:8000/?pin=8421`
   - Cookie: `assetdrop_pin=8421`
5. The PWA mobile client provides an on-screen PIN entry dialog that automatically stores the PIN in `localStorage` and includes it in all subsequent queue requests.
6. Constant-time validation (`secrets.compare_digest`) prevents timing side-channel attacks.

---

## 6. Headless Service Lifecycle Management

AssetDrop includes dedicated Windows automation scripts for completely silent background operation.

| Script | Purpose | Execution |
|---|---|---|
| `start_silent.vbs` | Starts server headlessly via `pythonw` | Double-click or run from cmd |
| `stop_server.bat` | Finds port 8000 listener via `netstat` and terminates process | Double-click or run from cmd |
| `setup_firewall.bat` | Adds Windows Defender inbound rule for port 8000 | Right-click -> Run as admin |

### Auto-Start on Windows Boot
To have AssetDrop start automatically every time you turn on your PC:
1. Press `Win + R`, type:
   ```
   shell:startup
   ```
   and press **Enter**. This opens your Windows Startup folder.
2. Right-click in the Startup folder -> **New** -> **Shortcut**.
3. Browse to `D:\AssetDrop\start_silent.vbs`.
4. Click **Next** and **Finish**.
5. AssetDrop will now start silently in the background whenever Windows boots, with zero user interaction required.

### Stopping the Server
When you need to stop or restart the server:
1. Double-click `D:\AssetDrop\stop_server.bat`.
2. The script searches for any active process listening on TCP port 8000 using `netstat -ano | findstr :8000 | findstr LISTENING`.
3. It safely terminates only the specific process (PID) listening on port 8000 using `taskkill /F /PID <pid>`, leaving all other Python tasks unaffected.
4. Output confirms:
   ```
   [AssetDrop] Found active process listening on port 8000 (PID: 14208). Terminating...
   [AssetDrop] Successfully terminated process (PID: 14208).
   [AssetDrop] AssetDrop server stopped successfully.
   ```

---

## 7. Troubleshooting & Diagnostic Matrix

| Symptom | Probable Cause | Diagnostic & Resolution |
|---|---|---|
| **Mobile browser cannot reach page (Timeout / ERR_CONNECTION_TIMED_OUT)** | Windows Firewall blocking Port 8000 | Run `setup_firewall.bat` as Administrator. Confirm rule exists: `netsh advfirewall firewall show rule name="AssetDrop Ingestion Server (Port 8000)"`. |
| | Mobile and PC on different Wi-Fi networks | Verify phone is connected to the same Wi-Fi SSID as PC, not cellular or guest network. |
| | Router AP Isolation enabled | Log into router settings, disable "AP Isolation", "Client Isolation", or "Guest Network Isolation". |
| | Server is not running | Double-click `start_silent.vbs`. Check listening status: `netstat -ano \| findstr :8000`. |
| **Port 8000 Conflict (Address already in use)** | Another application or previous Uvicorn instance using port 8000 | Run `stop_server.bat` to clear port 8000 listeners, then re-launch `start_silent.vbs`. |
| **Tailscale Remote Access Not Connecting** | Tailscale client disconnected on PC or phone | Open Tailscale app on phone and PC, verify both show green/connected state and belong to same account. |
| **Media Downloads Fail or Stay Queued** | `ffmpeg` or `gallery-dl` missing | Ensure `ffmpeg.exe` and `gallery-dl` are installed. Run `where ffmpeg` and `python -m gallery_dl --version`. |
| **Workstation Sleep / Standby Disconnects Server** | Windows enters Modern Standby or sleep when idle | Open Windows Settings -> **Power & battery** -> Set **When plugged in, put my device to sleep after** to **Never** (or adjust screen off to blank display without sleeping CPU). |
| **PIN Authorization Rejection (401 Unauthorized)** | PIN configured in `config.json` doesn't match client | Enter the correct PIN in the mobile client or append `?pin=<your_pin>` to the URL. |

---

## 8. Summary of Connection URLs

| Network Context | Sample Access URL |
|---|---|
| **Local Host Workstation** | `http://127.0.0.1:8000` or `http://localhost:8000` |
| **Local Wi-Fi LAN (Mobile)** | `http://192.168.220.36:8000` |
| **Remote 4G/5G Cellular (Tailscale)** | `http://100.x.y.z:8000` (e.g., `http://100.85.120.40:8000`) |
| **PIN-Protected Quick Bookmark** | `http://192.168.220.36:8000/?pin=YOUR_PIN` |

---
*AssetDrop Documentation Version 2.0 — Headless Ingestion Engine*
