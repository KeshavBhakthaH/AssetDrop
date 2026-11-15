# AssetDrop — Native Mobile App (Android & iOS)

This directory contains the native mobile wrapper for **AssetDrop**, built with **Capacitor** to deliver a true native app experience on Android and iOS.

---

## ⚡ The Killer Feature: Native Android Share Sheet Target

AssetDrop registers an `android.intent.action.SEND` filter inside `AndroidManifest.xml`.

When you are watching a video on:
- **Instagram Reels**
- **TikTok**
- **YouTube / Shorts**
- **Pinterest**
- **Twitter / X**

Simply tap **Share** inside that app $\rightarrow$ choose **AssetDrop**.
The app immediately receives the shared link, selects your preset, and shoots the media directly to your PC editing drive (`D:\Assets`) over local Wi-Fi!

---

## Prerequisites

- [Node.js](https://nodejs.org) (v18+)
- [Android Studio](https://developer.android.com/studio) (for compiling the Android APK)

---

## Quick Start: Build & Run on Android

1. **Install Dependencies**:
   ```bash
   cd mobile
   npm install
   ```

2. **Sync Web Assets & Capacitor**:
   ```bash
   npm run cap:sync
   ```

3. **Open in Android Studio**:
   ```bash
   npm run cap:open
   ```

4. **Run or Generate APK**:
   * Click **Run** (Green Play Button) in Android Studio to install directly onto your connected phone via USB / Wi-Fi debugging.
   * Or go to **Build $\rightarrow$ Build Bundle(s) / APK(s) $\rightarrow$ Build APK(s)** to generate a standalone `.apk` installable on any Android phone.

---

## Architecture & Configuration

* `capacitor.config.json`: Native app configuration (Cleartext HTTP enabled for local LAN access).
* `android/app/src/main/AndroidManifest.xml`: Android manifest with native `SEND` intent filter.
* `www/`: Static bundle compiled from `d:/AssetDrop/static/`.
