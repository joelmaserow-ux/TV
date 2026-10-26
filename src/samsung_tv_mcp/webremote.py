"""A family remote: a web page any phone or laptop on the home Wi-Fi can open.

Run `samsung-tv remote`, then open the printed address on each device. A short PIN keeps
guests on the Wi-Fi (and anything else on the network) from controlling the TV.
"""

from __future__ import annotations

import hmac
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import keymap, netflix
from .config import Settings
from .encrypted import credentials_path
from .legacy import TVError, normalize_key
from .tv import TV

PAGE = (Path(__file__).parent / "remote.html").read_text(encoding="utf-8")


class RemoteApp:
    def __init__(self, tv: TV, pin: str):
        self.tv = tv
        self.pin = pin
        # One command at a time: the TV protocols don't like overlapping connections.
        self.lock = threading.Lock()
        self.found_apps: list[dict] | None = None

    def discover_apps(self) -> None:
        """Look up which apps the TV can open (runs in the background at startup)."""
        from .apps import find_apps

        try:
            self.tv.wait_for_apps(timeout=30)
            self.found_apps = find_apps(self.tv.dial)
        except TVError:
            self.found_apps = []
        print("Apps this TV can open: " + (", ".join(a["name"] for a in self.found_apps) or "none found"), flush=True)

    def handle(self, body: dict) -> str:
        action = body.get("action")
        with self.lock:
            match action:
                case "key":
                    keys = [normalize_key(k) for k in body.get("keys", [])][:20]
                    self.tv.press(keys, delay=0.3)
                    return ""
                case "volume":
                    return self.tv.set_volume(int(body["level"]))
                case "step":
                    return self.tv.step_volume(int(body["steps"]))
                case "get_volume":
                    return self.tv.get_volume()
                case "mute":
                    return self.tv.set_mute(None)
                case "off":
                    return self.tv.power_off()
                case "app":
                    return self.tv.open_app(str(body["name"]))
                case "youtube":
                    return self.tv.play_youtube(str(body["url"]))
                case "netflix_profile":
                    return netflix.open_as(self.tv, str(body["profile"]))
                case "youtube_link":
                    return self.tv.link_youtube(str(body["code"]))
                case "search":
                    from .youtube_search import search
                    return json.dumps(search(str(body.get("query", ""))[:200]))
                case "status":
                    return self.tv.status()
                case "capabilities":
                    data = keymap.load(self.tv.s.host)
                    return json.dumps({
                        "unsupported": keymap.unsupported(data),
                        "found_apps": self.found_apps,
                        "netflix_profiles": netflix.load(self.tv.s.host)["profiles"]
                        if any(a["id"] == "Netflix" for a in self.found_apps or []) else [],
                        "apps": data.get("apps", {}),
                        "typing": data.get("typing"),
                    })
        raise ValueError(f"Unknown action {action!r}")


QUIET_ACTIONS = {"status", "get_volume", "capabilities"}


def _log(handler, body: dict, outcome: str, message: str) -> None:
    """One line per action in the remote's window, so failures are visible on the computer."""
    action = body.get("action", "?")
    if action in QUIET_ACTIONS and outcome == "ok":
        return
    detail = ",".join(body.get("keys", [])) if action == "key" else ""
    who = handler.client_address[0]
    line = f"{time.strftime('%H:%M:%S')}  {who:<15} {action} {detail}".rstrip()
    print(f"{line}  -> {outcome}" + (f": {message}" if message and outcome != "ok" else ""), flush=True)


def make_handler(app: RemoteApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionError, OSError):
                pass  # the phone gave up waiting (screen locked, page reloaded); nothing to do

        def _json(self, code: int, data: dict) -> None:
            self._send(code, json.dumps(data).encode(), "application/json")

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self._send(404, b"Not found", "text/plain")

        def do_POST(self):
            if self.path != "/api":
                return self._send(404, b"Not found", "text/plain")
            if not hmac.compare_digest(self.headers.get("X-Remote-Pin", ""), app.pin):
                return self._json(401, {"ok": False, "message": "Wrong PIN"})
            try:
                length = min(int(self.headers.get("Content-Length", 0)), 10_000)
                body = json.loads(self.rfile.read(length) or b"{}")
                message = app.handle(body)
                self._json(200, {"ok": True, "message": message})
                _log(self, body, "ok", message)
            except (TVError, ValueError, KeyError) as exc:
                self._json(200, {"ok": False, "message": str(exc)})
                _log(self, body if "body" in locals() else {}, "FAILED", str(exc))
            except Exception as exc:  # never leave a phone hanging on an unexpected error
                self._json(500, {"ok": False, "message": f"Something went wrong: {type(exc).__name__}: {exc}"})
                _log(self, body if "body" in locals() else {}, "ERROR", f"{type(exc).__name__}: {exc}")

    return Handler


def lan_ip(tv_host: str) -> str:
    """This computer's address on the TV's network, which is what phones should open."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect((tv_host, 9))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def load_pin(host: str, pin: str | None = None) -> str:
    """The family PIN. Kept between runs so phones that already unlocked stay unlocked."""
    path = credentials_path(host).with_name("remote-pin")
    if pin:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pin)
        return pin
    try:
        saved = path.read_text().strip()
        if saved:
            return saved
    except OSError:
        pass
    pin = f"{secrets.randbelow(10000):04d}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pin)
    return pin


def serve(port: int = 8765, pin: str | None = None) -> None:
    settings = Settings.from_env()
    pin = load_pin(settings.host, pin)
    app = RemoteApp(TV(settings), pin)
    threading.Thread(target=app.discover_apps, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(app))
    print("Family TV remote is running.\n")
    print(f"  Open on any phone or laptop on your Wi-Fi:  http://{lan_ip(settings.host)}:{port}")
    print(f"  PIN: {pin}\n")
    print("Keep this window open. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
