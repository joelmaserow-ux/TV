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
    def __init__(self, state):
        self.state, self.stopped = state, []

    def status(self, name):
        return self.state

    def stop(self, name):
        self.stopped.append(name)


class FakeTV:
    def __init__(self, state):
        self.s = type("S", (), {"host": "h"})()
        self.dial = FakeDial(state)
        self.launched, self.pressed = [], []

    def _launch(self, name, params=""):
        self.launched.append(name)

    def press(self, keys, delay=0.4):
        self.pressed.append(keys)


def test_open_as_restarts_running_netflix(monkeypatch):
    slept = []
    monkeypatch.setattr(netflix.time, "sleep", slept.append)
    tv = FakeTV("running")
    assert netflix.open_as(tv, "bianca") == "Opened Netflix as Bianca."
    assert tv.dial.stopped == ["Netflix"] and tv.launched == ["Netflix"]
    assert tv.pressed == [["KEY_UP"] * 5 + ["KEY_DOWN"] + ["KEY_ENTER"]]
    assert slept == [3, 15.0]


def test_profiles_and_wait_are_configurable(monkeypatch):
    monkeypatch.setattr(netflix.time, "sleep", lambda s: None)
    netflix.set_profiles("h", ["Mum", "Dad"])
    data = netflix.load("h")
    data["startup_wait"] = 22
    netflix.save("h", data)
    tv = FakeTV("stopped")
    netflix.open_as(tv, "Dad")
    assert tv.dial.stopped == [] and tv.pressed == [["KEY_UP", "KEY_UP", "KEY_DOWN", "KEY_ENTER"]]
