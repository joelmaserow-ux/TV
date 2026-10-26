import pytest

from samsung_tv_mcp import netflix


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))


def test_profile_keys():
    profiles = ["Jad", "Bianca", "Lee", "Ben", "Joel"]
    assert netflix.profile_keys(profiles, "joel") == ["KEY_DOWN"] * 6 + ["KEY_ENTER"]
    assert netflix.profile_keys(profiles, "Ben") == ["KEY_DOWN"] * 6 + ["KEY_UP"] + ["KEY_ENTER"]
    assert netflix.profile_keys(profiles, "Jad") == ["KEY_DOWN"] * 6 + ["KEY_UP"] * 4 + ["KEY_ENTER"]
    with pytest.raises(ValueError, match="No Netflix profile"):
        netflix.profile_keys(profiles, "Sam")


class FakeDial:
    """Netflix's DIAL state: running once launched, stopped once Exit -> Right -> OK lands."""

    def __init__(self, tv):
        self.tv = tv

    def status(self, name):
        return self.tv.netflix_state


class FakeTV:
    def __init__(self, ignore_exits=0):
        self.s = type("S", (), {"host": "h"})()
        self.events = []
        self.netflix_state = "stopped"
        self.ignore_exits = ignore_exits  # Exit presses lost while Netflix is still loading
        self.dial = FakeDial(self)

    def _launch(self, name, params=""):
        self.events.append(("launch", name))
        self.netflix_state = "running"

    def press(self, keys, delay=0.4):
        self.events.append(("press", keys))
        recent = [e[1][0] for e in self.events[-3:] if e[0] == "press"]
        if recent == ["KEY_EXIT", "KEY_RIGHT", "KEY_ENTER"]:
            if self.ignore_exits:
                self.ignore_exits -= 1
            else:
                self.netflix_state = "stopped"


def _fake_clock(monkeypatch):
    clock = [0.0]
    slept = []
    monkeypatch.setattr(netflix.time, "monotonic", lambda: clock[0])

    def sleep(t):
        slept.append(t)
        clock[0] += t

    monkeypatch.setattr(netflix.time, "sleep", sleep)
    return slept


def test_open_as_quits_netflix_properly_then_picks_profile(monkeypatch):
    slept = _fake_clock(monkeypatch)
    tv = FakeTV()
    assert netflix.open_as(tv, "bianca") == "Opened Netflix as Bianca."
    assert tv.events == [
        ("launch", "Netflix"),
        ("press", ["KEY_EXIT"]),
        ("press", ["KEY_RIGHT"]),  # "Are you sure you want to exit Netflix?" -> Yes
        ("press", ["KEY_ENTER"]),
        ("launch", "Netflix"),
    ] + [("press", [k]) for k in ["KEY_DOWN"] * 6 + ["KEY_UP"] * 3 + ["KEY_ENTER"]]
    assert slept[:5] == [15.0, 1.5, 0.5, 2, 20.0] and set(slept[5:]) == {0.6}


def test_profiles_and_wait_are_configurable(monkeypatch):
    slept = _fake_clock(monkeypatch)
    netflix.set_profiles("h", ["Mum", "Dad"])
    data = netflix.load("h")
    data["startup_wait"], data["profile_wait"] = 22, 30
    netflix.save("h", data)
    tv = FakeTV()
    netflix.open_as(tv, "Mum")
    presses = [e[1][0] for e in tv.events if e[0] == "press"][3:]
    assert presses == ["KEY_DOWN"] * 3 + ["KEY_UP", "KEY_ENTER"]
    assert slept[0] == 22 and slept[4] == 30


def test_unknown_profile_presses_nothing():
    tv = FakeTV()
    with pytest.raises(ValueError):
        netflix.open_as(tv, "Sam")
    assert tv.events == []


def test_normalize_title():
    assert netflix.normalize_title("  Rick & Morty: Season 7! ") == "rick and morty season 7"
    assert netflix.normalize_title("Amélie") == "amelie"


def test_type_keys_walks_the_keyboard():
    R, L, U, D, OK = "KEY_RIGHT", "KEY_LEFT", "KEY_UP", "KEY_DOWN", "KEY_ENTER"
    # a -> r is 5 right, 2 down; r -> i is 3 left, 1 up.
    assert netflix.type_keys("ri") == [R] * 5 + [D] * 2 + [OK] + [L] * 3 + [U] + [OK]
    # Space always from the "a" column: up, OK, back down onto "a".
    assert netflix.type_keys("b b") == [R, OK, L, U, OK, D, R, OK]
    assert netflix.type_keys("a0") == [OK] + [R] * 5 + [D] * 5 + [OK]


def test_type_keys_types_rick_and_morty():
    # Replay the presses on a model of the keyboard and read back what got typed.
    rows = [" "] + netflix.KEYBOARD  # row 0: the wide Space key
    r, c, typed = 1, 0, ""
    for key in netflix.type_keys("Rick and Morty"):
        if key == "KEY_RIGHT": c += 1
        elif key == "KEY_LEFT": c -= 1
        elif key == "KEY_DOWN": r += 1
        elif key == "KEY_UP": r -= 1
        else:
            typed += " " if r == 0 else rows[r][c]
        assert 0 <= r <= 6 and 0 <= c <= 5  # never leaves the keyboard
        if r == 0:
            assert c == 0
    assert typed == "rick and morty"


def test_watch_opens_profile_then_searches(monkeypatch):
    _fake_clock(monkeypatch)
    tv = FakeTV()
    msg = netflix.watch(tv, "Ben", "Rick and Morty")
    assert "Ben" in msg and "rick and morty" in msg
    presses = [e[1][0] for e in tv.events if e[0] == "press"]
    after_profile = presses[presses.index("KEY_ENTER", 4) + 1:]  # first OK after the exit dialog is the profile pick
    typing = netflix.type_keys("rick and morty")
    finish = netflix.to_first_result((4, 0))  # ends on "y"
    assert after_profile[:3] == netflix.TO_SEARCH
    assert after_profile[3:3 + len(typing)] == typing
    assert after_profile[3 + len(typing):] == finish


def test_to_first_result_goes_via_space_and_backspace():
    U, L, R, OK = "KEY_UP", "KEY_LEFT", "KEY_RIGHT", "KEY_ENTER"
    # From "y" (row 4, col 0): up 4 to "a", up onto Space, right to Backspace, right to the result.
    assert netflix.to_first_result((4, 0)) == [U] * 4 + [U, R, R, OK]
    # From "x" (row 3, col 5): left 5, up 3, then the same.
    assert netflix.to_first_result((3, 5)) == [L] * 5 + [U] * 3 + [U, R, R, OK]


def test_watch_without_title_just_opens_profile(monkeypatch):
    _fake_clock(monkeypatch)
    tv = FakeTV()
    assert netflix.watch(tv, "Joel") == "Opened Netflix as Joel."


def test_exit_is_retried_until_netflix_really_quits(monkeypatch):
    _fake_clock(monkeypatch)
    tv = FakeTV(ignore_exits=1)
    netflix.open_as(tv, "Joel")
    presses = [e[1][0] for e in tv.events if e[0] == "press"]
    assert presses[:6] == ["KEY_EXIT", "KEY_RIGHT", "KEY_ENTER"] * 2
    assert [e for e in tv.events if e[0] == "launch"] == [("launch", "Netflix")] * 2


def test_gives_up_without_pressing_profile_keys_if_netflix_never_quits(monkeypatch):
    _fake_clock(monkeypatch)
    tv = FakeTV(ignore_exits=99)
    with pytest.raises(netflix.TVError, match="didn't quit"):
        netflix.open_as(tv, "Joel")
    assert "KEY_DOWN" not in [e[1][0] for e in tv.events if e[0] == "press"]


def test_tv_that_never_reports_running_gets_one_exit(monkeypatch):
    _fake_clock(monkeypatch)
    tv = FakeTV()
    tv._launch = lambda name, params="": tv.events.append(("launch", name))  # state stays "stopped"
    netflix.open_as(tv, "Joel")
    presses = [e[1][0] for e in tv.events if e[0] == "press"]
    assert presses[:3] == ["KEY_EXIT", "KEY_RIGHT", "KEY_ENTER"] and presses[3] == "KEY_DOWN"


def test_home_wait_is_15s_and_old_saved_default_is_ignored(tmp_path, monkeypatch):
    import json
    assert netflix.load("h")["home_wait"] == 15.0
    # A file written by the old version saved every default, including home_wait 10.
    (tmp_path / "h.netflix.json").write_text(json.dumps({"home_wait": 10.0, "profile_wait": 30}))
    data = netflix.load("h")
    assert data["home_wait"] == 15.0 and data["profile_wait"] == 30
    netflix.save("h", data)
    assert json.loads((tmp_path / "h.netflix.json").read_text()) == {"profile_wait": 30}


def test_watch_waits_home_wait_before_search(monkeypatch):
    slept = _fake_clock(monkeypatch)
    tv = FakeTV()
    netflix.watch(tv, "Ben", "rick")
    assert 15.0 in slept
