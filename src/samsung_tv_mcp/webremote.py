"""A family remote: a web page any phone or laptop on the home Wi-Fi can open.

Run `samsung-tv remote`, then open the printed address on each device. A short PIN keeps
guests on the Wi-Fi (and anything else on the network) from controlling the TV.
"""

from __future__ import annotations

import hmac
import json
import os
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
    def __init__(self, tv: TV, pin: str, projector=None):
        self.tv = tv
        self.projector = projector
        self.pin = pin
        # One command at a time: the TV protocols don't like overlapping connections.
        self.lock = threading.Lock()
        self.found_apps: list[dict] | None = None
        self.job: str | None = None
        self.job_result: dict | None = None

    def discover_apps(self) -> None:
        """Look up which apps the TV can open (runs in the background at startup)."""
        from .apps import find_apps

        try:
            self.tv.wait_for_apps(timeout=30)
            self.found_apps = find_apps(self.tv.dial)
        except TVError:
            self.found_apps = []
        print("Apps this TV can open: " + (", ".join(a["name"] for a in self.found_apps) or "none found"), flush=True)

    def device(self, body: dict):
        """The Samsung TV, or the projector when the page asks for it."""
        if body.get("device") == "projector":
            if self.projector is None:
                raise TVError("No projector is set up. Start the remote with --projector <its IP>.")
            return self.projector
        return self.tv

    def start_job(self, fn, *args, label: str, device=None) -> str:
        """Run a long TV routine (like the Netflix search) in the background.

        It takes the TV lock for its whole run, so other buttons can't interleave key presses
        with it; they get a "busy" message instead of hanging.
        """
        if self.job is not None:
            raise TVError(f"Busy: {self.job}. Wait for it to finish.")
        self.job, self.job_result = label, None

        def run():
            try:
                with self.lock:
                    self.job_result = {"ok": True, "message": fn(device or self.tv, *args)}
            except Exception as exc:
                self.job_result = {"ok": False, "message": str(exc)}
            finally:
                self.job = None
                print(f"{time.strftime('%H:%M:%S')}  {label} -> {self.job_result['message']}", flush=True)

        threading.Thread(target=run, daemon=True).start()
        return f"{label}… this takes 1–2 minutes. Leave the remote alone until it's done."

    def handle(self, body: dict) -> str:
        action = body.get("action")
        if self.job is not None and action not in ("status", "get_volume", "capabilities", "job", "search", "netflix_find", "netflix_episodes", "devices", "channels", "channel_videos"):
            raise TVError(f"Busy: {self.job}. Wait for it to finish.")
        # These don't press keys, so they never wait behind a long job holding the lock.
        if action in ("netflix_watch", "job", "status", "get_volume", "capabilities", "search", "netflix_find", "netflix_episodes", "devices", "channels", "channel_videos"):
            return self._handle(body)
        with self.lock:
            return self._handle(body)

    def _handle(self, body: dict) -> str:
        action = body.get("action")
        dev = self.device(body)
        projector = dev is self.projector
        match action:
            case "key":
                keys = [normalize_key(k) for k in body.get("keys", [])][:20]
                dev.press(keys, delay=0.3)
                return ""
            case "volume":
                return dev.set_volume(int(body["level"]))
            case "step":
                return dev.step_volume(int(body["steps"]))
            case "get_volume":
                return dev.get_volume()
            case "mute":
                return dev.set_mute(None)
            case "off":
                return dev.power_off()
            case "app":
                return dev.open_app(str(body["name"]))
            case "youtube":
                return dev.play_youtube(str(body["url"]))
            case "netflix_watch":
                season = int(body["season"]) if body.get("season") else None
                episode = int(body["episode"]) if body.get("episode") else None
                what = str(body.get("show", ""))
                if what and (season or episode):
                    what += f" S{season or 1} E{episode or 1}"
                return self.start_job(
                    netflix.watch, str(body["profile"]), str(body.get("show", "")), season, episode,
                    bool(body.get("play")), device=dev,
                    label=("Projector: " if projector else "") + "Opening Netflix" + (f" for {what}" if what else ""))
            case "netflix_episodes":
                from .episodes import seasons
                return json.dumps(seasons(str(body.get("title", ""))[:100], body.get("year") or None))
            case "netflix_find":
                from .netflix_search import search as find
                return json.dumps(find(str(body.get("query", ""))[:100]))
            case "job":
                return json.dumps({"busy": self.job is not None, "last": self.job_result})
            case "youtube_link":
                return dev.link_youtube(str(body["code"]))
            case "search":
                from .youtube_search import search
                return json.dumps(search(str(body.get("query", ""))[:200]))
            case "channels":
                from .youtube_search import search_channels
                return json.dumps(search_channels(str(body.get("query", ""))[:200]))
            case "channel_videos":
                from .youtube_search import channel_videos
                return json.dumps(channel_videos(str(body.get("channel", ""))[:40]))
            case "status":
                return dev.status()
            case "on":
                if not projector:
                    raise TVError("This TV can't be turned on over the network; use its remote.")
                return dev.power_on()
            case "devices":
                return json.dumps(["tv"] + (["projector"] if self.projector else []))
            case "capabilities":
                from . import youtube
                linked = youtube.is_linked(dev.s.host)
                if projector:
                    return json.dumps({
                        "unsupported": [], "found_apps": dev.apps(), "volume_max": dev.volume_max(),
                        "netflix_profiles": netflix.load(dev.s.host)["profiles"], "power_on": True,
                        "youtube_linked": linked,
                    })
                data = keymap.load(self.tv.s.host)
                return json.dumps({
                    "unsupported": keymap.unsupported(data),
                    "found_apps": self.found_apps,
                    "netflix_profiles": netflix.load(self.tv.s.host)["profiles"]
                    if any(a["id"] == "Netflix" for a in self.found_apps or []) else [],
                    "volume_max": 100,
                    "power_on": False,
                    "youtube_linked": linked,
                })
        raise ValueError(f"Unknown action {action!r}")


QUIET_ACTIONS = {"status", "get_volume", "capabilities", "job", "devices"}


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


def projector_host(host: str, given: str | None = None) -> str | None:
    """The projector's IP: given now (and remembered), $GOOGLE_TV_HOST, or remembered earlier."""
    path = credentials_path(host).with_name("remote-projector")
    if given:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(given.strip())
        return given.strip()
    if os.environ.get("GOOGLE_TV_HOST"):
        return os.environ["GOOGLE_TV_HOST"].strip()
    try:
        return path.read_text().strip() or None
    except OSError:
        return None


def serve(port: int = 8765, pin: str | None = None, projector: str | None = None) -> None:
    settings = Settings.from_env()
    pin = load_pin(settings.host, pin)
    projector_ip = projector_host(settings.host, projector)
    device = None
    if projector_ip:
        from .googletv import Projector

        device = Projector(projector_ip)
    app = RemoteApp(TV(settings), pin, device)
    threading.Thread(target=app.discover_apps, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(app))
    print("Family TV remote is running.\n")
    print(f"  Open on any phone or laptop on your Wi-Fi:  http://{lan_ip(settings.host)}:{port}")
    print(f"  PIN: {pin}")
    print(f"  Projector: {projector_ip}" if projector_ip else "  Projector: not set up (add --projector <IP>)")
    print()
    print("Keep this window open. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
