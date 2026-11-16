# 🚀 AssetDrop: Cross-Device Media Ingestion Workstation

[![GitHub Release](https://img.shields.io/github/v/release/KeshavBhakthaH/AssetDrop?color=10b981&label=Release)](https://github.com/KeshavBhakthaH/AssetDrop/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Android%20%7C%20iOS%20%7C%20Web-emerald)](https://github.com/KeshavBhakthaH/AssetDrop)
[![E2E Verification](https://img.shields.io/badge/Tests-102%2F102%20Passing-brightgreen)](verify_e2e.py)

**AssetDrop** is an ultra-fast, local-first cross-device media ingestion engine built for video editors, content creators, and post-production studios. It allows editors to queue video clips, reels, sound effects, and music directly from their phones (iOS / Android) onto their local PC editing storage over Wi-Fi without cloud uploads, tedious pairing, or friction.

---

## 📦 Download & Quick Install

### 📱 Mobile App (Android & iOS)
- **Android Native App**: [⬇️ Download AssetDrop-mobile.apk (Latest)](https://github.com/KeshavBhakthaH/AssetDrop/releases/latest/download/AssetDrop-mobile.apk)
  - Features the **Native Android Share Sheet Target**: Tap *Share* on Instagram, YouTube, TikTok, Reddit, or X $\rightarrow$ select *AssetDrop* to shoot the video straight to your PC!
- **iOS & Android PWA (Zero Install)**:
  - Connect your phone to your PC's Wi-Fi network, open `http://<PC_LAN_IP>:8000` in Safari or Chrome, and tap **📲 Install App (PWA)** or **Add to Home Screen**.

### 🖥️ Windows PC App
- **Windows Portable Release**: [⬇️ Download AssetDrop-Windows.zip (Latest)](https://github.com/KeshavBhakthaH/AssetDrop/releases/latest/download/AssetDrop-Windows.zip)
  - Extract anywhere and double-click `setup.bat` (one-click installer that sets up dependencies, firewall, and desktop shortcut), or double-click `AssetDrop.exe`!

---

## ⚡ Super-Lightweight Architecture

AssetDrop is engineered from scratch for minimum system overhead:
- **PC Desktop Window**: Uses the native **Microsoft Edge WebView2** runtime built into Windows 10/11. No heavy Electron bloatware (~150MB+ saved; runs in ~25–40MB RAM).
- **Mobile Client**: Uses native **Android System WebView**. Total APK size is only ~11MB with 0MB cloud overhead.
- **Background System Tray**: Closes quietly to the Windows System Tray with quick controls (Open Dashboard, Open Downloads, Copy LAN URL, Quit).

---

## 🛠️ Step-by-Step Installation for Anyone in the World

### 1. Prerequisites
- **Operating System**: Windows 10/11 (or macOS / Linux for headless server)
- **Python**: 3.10+ installed ([python.org](https://python.org))

### 2. Quick Setup (Windows)
1. Clone or download this repository:
   ```powershell
   git clone https://github.com/KeshavBhakthaH/AssetDrop.git
   cd AssetDrop
   ```
2. Double-click **`setup.bat`**:
   - Automatically installs required Python packages (`pip install -r requirements.txt`).
   - Automatically installs FFmpeg via `winget` if missing.
   - Configures the Windows Firewall rule for Port 8000.
   - Creates an **AssetDrop** shortcut with icon on your Desktop.
   - Launches the native workstation application!

### 3. Manual Startup
```powershell
# Run the native desktop window with system tray:
python desktop_app.py

# Or run the headless background server:
python server.py
```

---

## 📱 How to Connect Your Phone

1. Ensure your PC and Phone are on the **same Wi-Fi network**.
2. Open the AssetDrop app on your phone (or browse to `http://<PC_IP>:8000/mobile`).
3. Enter the **5-digit Server UID** and **Connection Password** shown on your PC Workstation Settings screen.
4. **Done!** You can now:
   - Browse nested subfolders on your PC and create new project folders directly from your phone.
   - Send videos, music, or sound effects directly into your chosen destination folders on your PC.
   - Use the native Android **Share** button from Instagram, YouTube, TikTok, Reddit, and Pinterest.

---

## 🔒 Security & Defense-in-Depth

- **Simple Unified Authentication**: Constant-time timing-attack safe credential verification (`secrets.compare_digest`).
- **Path Traversal Protection**: Real-path boundary enforcement strictly isolates file operations within approved shared folders.
- **SSRF & Domain Verification**: Blocks localhost, loopback, private RFC-1918 subnets, and unapproved web domains.
- **Disk Protection**: Enforces a minimum 1GB free disk space floor before accepting downloads.

---

## 🧪 Testing & Verification

Run the full automated 4-tier test suite:

```powershell
python verify_e2e.py
```

**All 102/102 automated tests pass with 100% success rate.**

---

## 📄 License

AssetDrop is licensed under the [MIT License](LICENSE). Free for personal, commercial, and open-source use.
