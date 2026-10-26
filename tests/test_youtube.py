import json

import pytest

from samsung_tv_mcp import youtube
from samsung_tv_mcp.config import Settings
from samsung_tv_mcp.tv import TV


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))


async def _no_sleep(_):
    pass


class FakeApi:
    calls = []
    drop = 0  # how many setPlaylist requests the "still loading" app ignores
    reports = True  # whether the TV sends nowPlaying on connect
    playing = None

    def __init__(self, listener=None):
        self.screen_name = "Living Room TV"
        self.listener = listener

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
        if self.listener and FakeApi.reports:
            state = type("S", (), {"name": "Playing" if FakeApi.playing else "Stopped"})()
            await self.listener.now_playing_changed(type("E", (), {"video_id": FakeApi.playing, "state": state})())
        return True

    async def _command(self, command, params):
        FakeApi.calls.append(("play", params["videoId"]))
        if FakeApi.drop:
            FakeApi.drop -= 1
        else:
            FakeApi.playing = params["videoId"]
        return command == "setPlaylist" and params["videoIds"] == params["videoId"]

    async def disconnect(self):
        FakeApi.calls.append(("disconnect",))


@pytest.fixture
def fake_api(monkeypatch):
    FakeApi.calls, FakeApi.drop, FakeApi.reports, FakeApi.playing = [], 0, True, None
    monkeypatch.setattr(youtube.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(youtube, "_api", FakeApi)
    return FakeApi


def test_link_then_play(fake_api, tmp_path):
    assert youtube.link("1.2.3.4", "123 456 789 012") == "Living Room TV"
    assert json.loads((tmp_path / "1.2.3.4.youtube.json").read_text())["screenId"] == "abc"
    assert youtube.play("1.2.3.4", "jNQXAC9IVRw") is True
    # No "terminate": it sends older TV apps back to the account picker.
    assert fake_api.calls == [("pair", "123456789012"), ("load", "abc"), ("play", "jNQXAC9IVRw")]


def test_play_resends_until_app_takes_it(fake_api):
    youtube.link("1.2.3.4", "123456789012")
    fake_api.drop = 2
    assert youtube.play("1.2.3.4", "jNQXAC9IVRw") is True
    assert [c for c in fake_api.calls if c[0] == "play"] == [("play", "jNQXAC9IVRw")] * 3


def test_play_without_now_playing_reports_sends_once(fake_api):
    youtube.link("1.2.3.4", "123456789012")
    fake_api.reports = False
    assert youtube.play("1.2.3.4", "jNQXAC9IVRw") is False
    assert [c for c in fake_api.calls if c[0] == "play"] == [("play", "jNQXAC9IVRw")]


def test_queued_but_stopped_is_not_playing():
    np = youtube._NowPlaying()
    np.video_id, np.state = "jNQXAC9IVRw", "Stopped"
    assert not np.is_playing("jNQXAC9IVRw")
    np.state = "Starting"
    assert np.is_playing("jNQXAC9IVRw")


def test_play_gives_up(fake_api):
    youtube.link("1.2.3.4", "123456789012")
    fake_api.drop = 99
    with pytest.raises(youtube.TVError, match="kept ignoring"):
        youtube.play("1.2.3.4", "jNQXAC9IVRw")


def test_link_rejects_short_code():
    with pytest.raises(ValueError):
        youtube.link("1.2.3.4", "12")


def test_tv_uses_lounge_when_linked(fake_api, monkeypatch):
    tv = TV(Settings(host="1.2.3.4", port=1, mac=None, client_name="t", client_id="t", use_cec=False,
                     timeout=1, rendering_control_url=None, dial_url="http://127.0.0.1:1/ws/app/"))
    youtube.link("1.2.3.4", "123456789012")
    monkeypatch.setattr(tv.dial, "status", lambda name: "running")
    monkeypatch.setattr(tv.dial, "ready", lambda: True)
    assert tv.play_youtube("https://youtu.be/jNQXAC9IVRw") == "Playing https://youtu.be/jNQXAC9IVRw on the TV."
    assert ("play", "jNQXAC9IVRw") in fake_api.calls


def test_fresh_youtube_presses_ok_on_account_picker(fake_api, monkeypatch):
    import samsung_tv_mcp.tv as tvmod
    tv = TV(Settings(host="1.2.3.4", port=1, mac=None, client_name="t", client_id="t", use_cec=False,
                     timeout=1, rendering_control_url=None, dial_url="http://127.0.0.1:1/ws/app/"))
    clock = [0.0]
    monkeypatch.setattr(tvmod.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(tvmod.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(tv, "wait_for_apps", lambda: None)
    monkeypatch.setattr(tv.dial, "status", lambda name: "stopped")
    monkeypatch.setattr(tv, "_launch", lambda name, params="": None)
    pressed = []
    monkeypatch.setattr(tv, "press", lambda keys, delay=0.4: pressed.extend(keys) or keys)
    # Comes online only after someone picks an account.
    monkeypatch.setattr(youtube, "is_online", lambda host: "KEY_ENTER" in pressed)
    tv._ensure_youtube_open()
    assert pressed == ["KEY_ENTER"]
