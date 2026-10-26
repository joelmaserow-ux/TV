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


class FakeTV:
    def __init__(self):
        self.s = type("S", (), {"host": "h"})()
        self.events = []

    def _launch(self, name, params=""):
        self.events.append(("launch", name))

    def press(self, keys, delay=0.4):
        self.events.append(("press", keys))


def test_open_as_quits_netflix_properly_then_picks_profile(monkeypatch):
    slept = []
    monkeypatch.setattr(netflix.time, "sleep", slept.append)
    tv = FakeTV()
    assert netflix.open_as(tv, "bianca") == "Opened Netflix as Bianca."
    assert tv.events == [
        ("launch", "Netflix"),
        ("press", ["KEY_EXIT"]),
        ("press", ["KEY_RIGHT"]),  # "Are you sure you want to exit Netflix?" -> Yes
        ("press", ["KEY_ENTER"]),
        ("launch", "Netflix"),
        ("press", ["KEY_UP"] * 5 + ["KEY_DOWN"] + ["KEY_ENTER"]),
    ]
    assert slept == [15.0, 1.5, 0.5, 3, 15.0]


def test_profiles_and_wait_are_configurable(monkeypatch):
    slept = []
    monkeypatch.setattr(netflix.time, "sleep", slept.append)
    netflix.set_profiles("h", ["Mum", "Dad"])
    data = netflix.load("h")
    data["startup_wait"] = 22
    netflix.save("h", data)
    tv = FakeTV()
    netflix.open_as(tv, "Dad")
    assert tv.events[-1] == ("press", ["KEY_UP", "KEY_UP", "KEY_DOWN", "KEY_ENTER"])
    assert slept[0] == slept[-1] == 22


def test_unknown_profile_presses_nothing():
    tv = FakeTV()
    with pytest.raises(ValueError):
        netflix.open_as(tv, "Sam")
    assert tv.events == []
