import pytest

from samsung_tv_mcp import netflix


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))


def test_profile_keys():
    profiles = ["Jad", "Bianca", "Lee", "Ben", "Joel"]
    assert netflix.profile_keys(profiles, "jad") == ["KEY_UP"] * 5 + ["KEY_ENTER"]
    assert netflix.profile_keys(profiles, "Ben") == ["KEY_UP"] * 5 + ["KEY_DOWN"] * 3 + ["KEY_ENTER"]
    with pytest.raises(ValueError, match="No Netflix profile"):
        netflix.profile_keys(profiles, "Sam")


class FakeDial:
    def __init__(self, state, stoppable=True):
        self.state, self.stopped, self.stoppable = state, [], stoppable

    def status(self, name):
        return self.state

    def stop(self, name):
        self.stopped.append(name)
        if self.stoppable:
            self.state = "stopped"


class FakeTV:
    def __init__(self, state):
        self.s = type("S", (), {"host": "h"})()
        self.dial = FakeDial(state)
        self.launched, self.pressed = [], []

    def _launch(self, name, params=""):
        self.launched.append(name)

    def press(self, keys, delay=0.4):
        self.pressed.append(keys)


def _fake_clock(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(netflix.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(netflix.time, "sleep", lambda t: clock.__setitem__(0, clock[0] + t))
    return clock


@pytest.mark.parametrize("state", ["running", "hidden"])
def test_open_as_always_restarts_netflix(monkeypatch, state):
    _fake_clock(monkeypatch)
    tv = FakeTV(state)
    assert netflix.open_as(tv, "bianca") == "Opened Netflix as Bianca."
    assert tv.dial.stopped == ["Netflix"] and tv.launched == ["Netflix"]
    assert tv.pressed == [["KEY_UP"] * 5 + ["KEY_DOWN"] + ["KEY_ENTER"]]


def test_close_falls_back_to_exit_key(monkeypatch):
    _fake_clock(monkeypatch)
    tv = FakeTV("hidden")
    tv.dial.stoppable = False
    real_press = tv.press

    def press(keys, delay=0.4):
        real_press(keys, delay)
        if keys == ["KEY_EXIT"]:
            tv.dial.state = "stopped"

    tv.press = press
    netflix.open_as(tv, "Joel")
    assert tv.pressed[0] == ["KEY_EXIT"] and tv.launched == ["Netflix"]


def test_close_gives_up_clearly(monkeypatch):
    _fake_clock(monkeypatch)
    tv = FakeTV("running")
    tv.dial.stoppable = False
    with pytest.raises(netflix.TVError, match="Couldn't close Netflix"):
        netflix.open_as(tv, "Joel")
    assert tv.launched == []


def test_profiles_and_wait_are_configurable(monkeypatch):
    monkeypatch.setattr(netflix.time, "sleep", lambda s: None)
    netflix.set_profiles("h", ["Mum", "Dad"])
    data = netflix.load("h")
    data["startup_wait"] = 22
    netflix.save("h", data)
    tv = FakeTV("stopped")
    netflix.open_as(tv, "Dad")
    assert tv.pressed == [["KEY_UP", "KEY_UP", "KEY_DOWN", "KEY_ENTER"]]
