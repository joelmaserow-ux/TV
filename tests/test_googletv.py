import pytest

from samsung_tv_mcp import googletv


def test_key_names_map_to_android_keycodes():
    assert googletv.to_keycode("KEY_ENTER") == "DPAD_CENTER"
    assert googletv.to_keycode("up") == "DPAD_UP"
    assert googletv.to_keycode("KEYCODE_HOME") == "HOME"
    assert googletv.to_keycode("KEY_7") == "7"
    with pytest.raises(ValueError):
        googletv.to_keycode("KEY_NOPE")


def test_every_mapped_key_is_a_real_android_keycode():
    for name in googletv.KEYS:
        googletv.to_keycode(name)


class FakeRemote:
    def __init__(self):
        self.sent = []
        self.is_on = True
        self.current_app = "com.netflix.ninja"
        self.volume_info = {"level": 10, "max": 20, "muted": False}
        self.device_info = {"manufacturer": "TOPTRO", "model": "TP3"}

    async def async_connect(self):
        pass

    def keep_reconnecting(self):
        pass

    def send_key_command(self, code):
        self.sent.append(("key", code))

    def send_text(self, text):
        self.sent.append(("text", text))

    def send_launch_app_command(self, target):
        self.sent.append(("launch", target))

    def disconnect(self):
        pass


@pytest.fixture
def gtv(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))
    fake = FakeRemote()
    g = googletv.GoogleTV("10.0.0.5")
    monkeypatch.setattr(g, "_make", lambda: fake)
    cert, key = googletv._files("10.0.0.5")
    cert.write_text("c"); key.write_text("k"); cert.with_suffix(".paired").write_text("ok")
    return g, fake


def test_commands(gtv):
    g, fake = gtv
    assert g.press(["KEY_UP", "ok"], delay=0) == ["DPAD_UP", "DPAD_CENTER"]
    g.type_text("rick and morty")
    assert g.launch("Disney+") == "com.disney.disneyplus"
    g.launch("https://www.netflix.com/title/80014749")
    assert fake.sent == [("key", "DPAD_UP"), ("key", "DPAD_CENTER"), ("text", "rick and morty"),
                         ("launch", "com.disney.disneyplus"), ("launch", "https://www.netflix.com/title/80014749")]
    assert g.status()["device"] == "TOPTRO TP3"


def test_set_volume_steps_on_device_scale(gtv):
    g, fake = gtv
    g.set_volume(75)  # 75% of max 20 = 15, from 10 -> 5 steps up
    assert fake.sent == [("key", "VOLUME_UP")] * 5


def test_unpaired_is_explained(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))
    with pytest.raises(googletv.TVError, match="Not paired"):
        googletv.GoogleTV("10.0.0.6").press(["KEY_UP"])
