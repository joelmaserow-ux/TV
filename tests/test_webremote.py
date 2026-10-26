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
