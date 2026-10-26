import json

import pytest

from samsung_tv_mcp import youtube
from samsung_tv_mcp.config import Settings
from samsung_tv_mcp.tv import TV


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))


class FakeApi:
    calls = []

    def __init__(self):
        self.screen_name = "Living Room TV"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def pair(self, code):
        FakeApi.calls.append(("pair", code))
        return True

    def store_auth_state(self):
        return {"version": 1, "screenId": "abc"}

    def load_auth_state(self, data):
        FakeApi.calls.append(("load", data["screenId"]))

    async def refresh_auth(self):
        return True

    async def is_available(self):
        return True

    async def connect(self):
        return True

    async def _command(self, command, params):
        FakeApi.calls.append(("play", params["videoId"]))
        return command == "setPlaylist" and params["videoIds"] == params["videoId"]

    async def seek_to(self, t):
        FakeApi.calls.append(("seek", t))

    async def disconnect(self):
        FakeApi.calls.append(("disconnect",))


@pytest.fixture
def fake_api(monkeypatch):
    FakeApi.calls = []
    monkeypatch.setattr(youtube, "_api", FakeApi)
    return FakeApi


def test_link_then_play(fake_api, tmp_path, monkeypatch):
    monkeypatch.setattr(youtube.asyncio, "sleep", _no_sleep)
    assert youtube.link("1.2.3.4", "123 456 789 012") == "Living Room TV"
    assert json.loads((tmp_path / "1.2.3.4.youtube.json").read_text())["screenId"] == "abc"
    youtube.play("1.2.3.4", "jNQXAC9IVRw")
    assert fake_api.calls == [("pair", "123456789012"), ("load", "abc"), ("play", "jNQXAC9IVRw"), ("disconnect",)]


def test_link_rejects_short_code():
    with pytest.raises(ValueError):
        youtube.link("1.2.3.4", "12")


async def _no_sleep(_):
    pass


def test_tv_uses_lounge_when_linked(fake_api, monkeypatch):
    monkeypatch.setattr(youtube.asyncio, "sleep", _no_sleep)
    tv = TV(Settings(host="1.2.3.4", port=1, mac=None, client_name="t", client_id="t", use_cec=False,
                     timeout=1, rendering_control_url=None, dial_url="http://127.0.0.1:1/ws/app/"))
    youtube.link("1.2.3.4", "123456789012")
    monkeypatch.setattr(tv.dial, "status", lambda name: "running")
    assert tv.play_youtube("https://youtu.be/jNQXAC9IVRw") == "Playing https://youtu.be/jNQXAC9IVRw on the TV."
    assert ("play", "jNQXAC9IVRw") in fake_api.calls
