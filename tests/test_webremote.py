import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from samsung_tv_mcp import webremote


class FakeRemote:
    def __init__(self):
        self.sent = []

    def send_keys(self, keys, delay=0.4):
        self.sent += keys
        return keys


class FakeTV:
    def __init__(self):
        self.remote = FakeRemote()
        self.s = type("S", (), {"host": "1.2.3.4"})()

    def press(self, keys, delay=0.4):
        from samsung_tv_mcp.legacy import normalize_key
        return self.remote.send_keys([normalize_key(k) for k in keys], delay)

    def set_volume(self, level):
        return f"Volume set to {level}."

    def status(self):
        return "The TV at 1.2.3.4 is on and accepting remote commands."


@pytest.fixture
def server():
    tv = FakeTV()
    app = webremote.RemoteApp(tv, "1234")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), webremote.make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", tv
    httpd.shutdown()


def post(base, body, pin="1234"):
    req = urllib.request.Request(base + "/api", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Remote-Pin": pin})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_page_served(server):
    base, _ = server
    with urllib.request.urlopen(base + "/") as r:
        assert b"TV Remote" in r.read()


def test_wrong_pin_rejected(server):
    base, tv = server
    assert post(base, {"action": "key", "keys": ["KEY_UP"]}, pin="0000")[0] == 401
    assert tv.remote.sent == []


def test_keys_and_volume(server):
    base, tv = server
    assert post(base, {"action": "key", "keys": ["up", "KEY_ENTER"]}) == (200, {"ok": True, "message": ""})
    assert tv.remote.sent == ["KEY_UP", "KEY_ENTER"]
    assert post(base, {"action": "volume", "level": 9})[1]["message"] == "Volume set to 9."


def test_bad_key_is_an_error_not_a_crash(server):
    base, _ = server
    code, data = post(base, {"action": "key", "keys": ["rm -rf"]})
    assert code == 200 and data["ok"] is False


def test_pin_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))
    first = webremote.load_pin("1.2.3.4")
    assert webremote.load_pin("1.2.3.4") == first
    assert webremote.load_pin("1.2.3.4", "4321") == "4321" == webremote.load_pin("1.2.3.4")


def test_search_action(server, monkeypatch):
    base, _ = server
    import samsung_tv_mcp.youtube_search as ys
    monkeypatch.setattr(ys, "search", lambda q: [{"id": "aqz-KE-bpKQ", "title": q, "channel": "c", "duration": "1:00"}])
    code, data = post(base, {"action": "search", "query": "bunny"})
    assert code == 200 and json.loads(data["message"])[0]["title"] == "bunny"


def test_youtube_link_action(server):
    base, tv = server
    tv.link_youtube = lambda code: f"Linked {code}"
    assert post(base, {"action": "youtube_link", "code": "123 456"})[1] == {"ok": True, "message": "Linked 123 456"}


def test_capabilities_include_found_apps(server):
    base, tv = server
    import samsung_tv_mcp.webremote as wr
    # The handler's app is reachable through the server fixture only via requests; set via action.
    code, data = post(base, {"action": "capabilities"})
    assert code == 200 and json.loads(data["message"])["found_apps"] is None


def test_netflix_watch_runs_in_background_and_blocks_other_keys(server, monkeypatch):
    import threading as th
    import samsung_tv_mcp.netflix as nf
    base, tv = server
    release = th.Event()

    def slow_watch(tv_, profile, show, season=None, episode=None, play=False, year=None, seasons=None):
        release.wait(5)
        return f"Opened Netflix as {profile}. Searched for {show}."

    monkeypatch.setattr(nf, "watch", slow_watch)
    code, data = post(base, {"action": "netflix_watch", "profile": "Ben", "show": "rick and morty"})
    assert data["ok"] and "1–2 minutes" in data["message"]
    # Keys are refused while it runs, but status still answers straight away.
    assert "Busy" in post(base, {"action": "key", "keys": ["KEY_UP"]})[1]["message"]
    assert post(base, {"action": "status"})[1]["ok"]
    assert json.loads(post(base, {"action": "job"})[1]["message"])["busy"] is True
    release.set()
    for _ in range(50):
        job = json.loads(post(base, {"action": "job"})[1]["message"])
        if not job["busy"]:
            break
        th.Event().wait(0.05)
    assert job["last"] == {"ok": True, "message": "Opened Netflix as Ben. Searched for rick and morty."}
    assert post(base, {"action": "key", "keys": ["KEY_UP"]})[1]["ok"]


def test_netflix_watch_passes_season_and_episode(server, monkeypatch):
    import samsung_tv_mcp.netflix as nf
    base, tv = server
    got = []
    monkeypatch.setattr(nf, "watch", lambda tv_, p, show, season, episode, play=False, year=None, seasons=None: got.append((p, show, season, episode, seasons)) or "ok")
    code, data = post(base, {"action": "netflix_watch", "profile": "Ben", "show": "Rick and Morty", "season": "2", "episode": "4", "seasons": 7})
    assert "S2 E4" in data["message"]
    for _ in range(50):
        if got:
            break
        __import__("time").sleep(0.05)
    assert got == [("Ben", "Rick and Morty", 2, 4, 7)]


class FakeProjector(FakeTV):
    def __init__(self):
        super().__init__()
        self.s = type("S", (), {"host": "192.168.0.71"})()
        self.on = False

    def power_on(self):
        self.on = True
        return "Sent power."

    def status(self):
        return f"The projector is {'on' if self.on else 'off'}."

    def apps(self):
        return [{"id": "disney+", "name": "Disney+"}]

    def volume_max(self):
        return 15


def test_device_switch_routes_to_projector(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))
    tv, proj = FakeTV(), FakeProjector()
    app = webremote.RemoteApp(tv, "1234", proj)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), webremote.make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        assert json.loads(post(base, {"action": "devices"})[1]["message"]) == ["tv", "projector"]
        post(base, {"action": "key", "keys": ["KEY_UP"], "device": "projector"})
        post(base, {"action": "key", "keys": ["KEY_DOWN"]})
        assert proj.remote.sent == ["KEY_UP"] and tv.remote.sent == ["KEY_DOWN"]
        caps = json.loads(post(base, {"action": "capabilities", "device": "projector"})[1]["message"])
        assert caps["volume_max"] == 15 and caps["found_apps"][0]["name"] == "Disney+" and caps["power_on"]
        assert post(base, {"action": "on", "device": "projector"})[1]["ok"] and proj.on
        assert "can't be turned on" in post(base, {"action": "on"})[1]["message"]
    finally:
        httpd.shutdown()


def test_no_projector_configured(server):
    base, _ = server
    assert json.loads(post(base, {"action": "devices"})[1]["message"]) == ["tv"]
    assert "No projector" in post(base, {"action": "key", "keys": ["KEY_UP"], "device": "projector"})[1]["message"]
