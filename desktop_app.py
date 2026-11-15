"""
desktop_app.py — AssetDrop Native Desktop Workstation Application.

Full PC App Window + Windows System Tray Integration:
- Native Microsoft Edge WebView2 desktop window (dark mode #09090b).
- Integrated background FastAPI daemon (:8000).
- Windows System Tray icon (pystray) with minimize-to-tray on close.
- Tray Quick Actions: Open Dashboard, Open D:/Assets, Copy LAN URL, Quit.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw
import pystray
import uvicorn
import webview

from core.config import PROJECT_ROOT, load_config

SERVER_PORT = 8000
SERVER_HOST = "0.0.0.0"


def get_local_lan_ip() -> str:
    """Discovers local Wi-Fi / LAN IPv4 address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def is_port_in_use(port: int = SERVER_PORT) -> bool:
    """Checks if port 8000 is already active."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def create_tray_icon_image() -> Image.Image:
    """Generates an obsidian & cyber emerald tray icon."""
    icon_path = Path(PROJECT_ROOT) / "static" / "icons" / "icon-192.png"
    if icon_path.exists():
        try:
            return Image.open(icon_path).resize((64, 64))
        except Exception:
            pass

    # Fallback procedural icon
    img = Image.new("RGBA", (64, 64), color=(9, 9, 11, 255))
    draw = ImageDraw.Draw(img)
    # Emerald rounded badge
    draw.rounded_rectangle([4, 4, 60, 60], radius=12, fill=(16, 185, 129, 255))
    # Downward ingestion arrow
    draw.polygon([(32, 48), (18, 28), (26, 28), (26, 14), (38, 14), (38, 28), (46, 28)], fill=(9, 9, 11, 255))
    return img


class AssetDropDesktopApp:
    def __init__(self):
        self.server_thread: Optional[threading.Thread] = None
        self.window: Optional[webview.Window] = None
        self.tray_icon: Optional[pystray.Icon] = None
        self.is_running = True
        self.local_ip = get_local_lan_ip()
        self.url = f"http://127.0.0.1:{SERVER_PORT}"
        self.mobile_url = f"http://{self.local_ip}:{SERVER_PORT}"

    def start_background_server(self):
        """Launches Uvicorn server in a background daemon thread if not already active."""
        if is_port_in_use(SERVER_PORT):
            print(f"[AssetDrop] Server already listening on port {SERVER_PORT}.")
            return

        def run_server():
            # Import server dynamically in thread
            from server import app
            config = uvicorn.Config(
                app=app,
                host=SERVER_HOST,
                port=SERVER_PORT,
                log_level="warning",
                access_log=False,
            )
            server = uvicorn.Server(config)
            server.run()

        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        print(f"[AssetDrop] Server started in background on {SERVER_HOST}:{SERVER_PORT}")

        # Wait briefly for startup
        for _ in range(30):
            if is_port_in_use(SERVER_PORT):
                break
            time.sleep(0.1)

    def on_window_closing(self):
        """Intercepts window close to minimize to system tray instead of exiting."""
        if self.window and self.is_running:
            self.window.hide()
            if self.tray_icon:
                try:
                    self.tray_icon.notify(
                        "AssetDrop is still running in the background tray.",
                        "AssetDrop Ingestion Active",
                    )
                except Exception:
                    pass
            return False  # Prevent window destruction
        return True

    def show_window(self):
        """Restores and focuses the main desktop app window."""
        if self.window:
            self.window.show()
            self.window.restore()

    def open_assets_folder(self):
        """Opens D:/Assets in Windows File Explorer."""
        assets_dir = Path("D:/Assets")
        if not assets_dir.exists():
            os.makedirs(assets_dir, exist_ok=True)
        os.startfile(assets_dir)

    def copy_lan_url(self):
        """Copies the phone connection URL to Windows clipboard."""
        try:
            import tkinter as tk
            r = tk.Tk()
            r.withdraw()
            r.clipboard_clear()
            r.clipboard_append(self.mobile_url)
            r.update()
            r.destroy()
            if self.tray_icon:
                self.tray_icon.notify(f"Copied to clipboard: {self.mobile_url}", "AssetDrop LAN URL")
        except Exception as e:
            print("Failed to copy to clipboard:", e)

    def quit_app(self):
        """Cleanly shuts down the app, tray icon, and background server."""
        self.is_running = False
        if self.tray_icon:
            self.tray_icon.stop()
        if self.window:
            self.window.destroy()
        sys.exit(0)

    def setup_tray(self):
        """Configures the Windows System Tray icon and context menu."""
        image = create_tray_icon_image()
        menu = pystray.Menu(
            pystray.MenuItem("🖥️ Open AssetDrop Dashboard", lambda: self.show_window(), default=True),
            pystray.MenuItem("📂 Open Assets Folder (D:\\Assets)", lambda: self.open_assets_folder()),
            pystray.MenuItem(f"📱 Copy Mobile URL ({self.local_ip})", lambda: self.copy_lan_url()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ Quit AssetDrop", lambda: self.quit_app()),
        )
        self.tray_icon = pystray.Icon("AssetDrop", image, "AssetDrop Ingestion Workstation", menu)

    def run(self):
        """Main application lifecycle runner."""
        # 1. Start background server
        self.start_background_server()

        # 2. Setup System Tray
        self.setup_tray()
        tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        tray_thread.start()

        # 3. Create native desktop window
        self.window = webview.create_window(
            title="AssetDrop // Workstation Engine",
            url=self.url,
            width=1120,
            height=780,
            min_size=(440, 600),
            background_color="#09090b",
            text_select=True,
            confirm_close=False,
        )

        # Hook close event to minimize to tray
        self.window.events.closing += self.on_window_closing

        # 4. Start GUI event loop (blocking)
        try:
            webview.start(debug=False)
        finally:
            self.is_running = False
            if self.tray_icon:
                self.tray_icon.stop()


def main():
    app = AssetDropDesktopApp()
    app.run()


if __name__ == "__main__":
    main()
