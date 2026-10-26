import pytest

from samsung_tv_mcp import buttontest, keymap
from samsung_tv_mcp.legacy import TVError


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))


def test_translate():
    data = {"keys": {"KEY_FF": "KEY_FF_", "KEY_GUIDE": None, "KEY_1": "KEY_1"}}
    assert keymap.translate(["KEY_FF", "KEY_UP", "KEY_7"], data) == ["KEY_FF_", "KEY_UP", "KEY_7"]
    with pytest.raises(TVError, match="KEY_GUIDE"):
        keymap.translate(["KEY_GUIDE"], data)
    assert "KEY_GUIDE" in keymap.unsupported(data)


class FakeTV:
    def __init__(self, works):
        self.works = works
        self.pressed = []
        self.s = type("S", (), {"host": "1.2.3.4"})()
        self.remote = self
        self.dial = type("D", (), {"status": lambda self, app: "stopped" if app == "YouTube" else "not available"})()

    def send_keys(self, keys, delay=0.4):
        self.pressed += keys


def test_button_test_learns_alternatives(monkeypatch):
    monkeypatch.setattr(buttontest.time, "sleep", lambda s: None)
    monkeypatch.setattr(buttontest, "type_text", lambda *a, **k: None)
    works = {"KEY_FF_", "KEY_POWER", "KEY_MENU"}
    tv = FakeTV(works)

    def ask(q):
        if q.strip().startswith("Press Enter"):
            return ""
        if "keyboard showing" in q:
            return "y"
        if "'abc'" in q:
            return "n"
        return "y" if tv.pressed and tv.pressed[-1] in works else "n"

    data = buttontest.run(tv, ask=ask, say=lambda s: None)
    assert data["keys"]["KEY_FF"] == "KEY_FF_"
    assert data["keys"]["KEY_POWEROFF"] == "KEY_POWER"
    assert data["keys"]["KEY_GUIDE"] is None
    assert data["apps"] == {"YouTube": True, "Netflix": False}
    assert data["typing"] is False
    assert keymap.load("1.2.3.4") == data


def test_retest_only_playback_and_typing(monkeypatch):
    monkeypatch.setattr(buttontest.time, "sleep", lambda s: None)
    typed = []
    monkeypatch.setattr(buttontest, "type_text", lambda host, text, *a: typed.append(text))
    keymap.save("1.2.3.4", {"keys": {"KEY_PAUSE": None, "KEY_MENU": "KEY_MENU"}, "typing": False})
    tv = FakeTV(set())
    answers = iter(["", "y", "y", "y"])  # setup Enter, Pause works, keyboard showing, abc appeared
    data = buttontest.run(tv, ask=lambda q: next(answers), say=lambda s: None, only=["Pause", "typing"])
    assert tv.pressed == ["KEY_PAUSE"] and typed == ["abc"]
    assert data["keys"] == {"KEY_PAUSE": "KEY_PAUSE", "KEY_MENU": "KEY_MENU"}
    assert data["typing"] is True


def test_playback_retest_starts_video_itself(monkeypatch):
    monkeypatch.setattr(buttontest.time, "sleep", lambda s: None)
    monkeypatch.setattr(buttontest.youtube, "is_linked", lambda host: True)
    tv = FakeTV(set())
    played = []
    tv.play_youtube = lambda url: played.append(url) or "Playing it."
    answers = iter(["y", "y"])  # video is playing, Pause works
    data = buttontest.run(tv, ask=lambda q: next(answers), say=lambda s: None, only=["Pause"])
    assert played == [buttontest.TEST_VIDEO]
    assert data["keys"]["KEY_PAUSE"] == "KEY_PAUSE"
