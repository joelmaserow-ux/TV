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
        # Pretend links open their app and packages are ignored, like the TP3's stick.
        if target.startswith("https://www.disneyplus.com"):
            self.current_app = "com.disney.disneyplus"

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
    assert g.launch("Disney Plus") == "Opened Disney Plus."
    assert g.launch("https://www.netflix.com/title/80014749") == "Opened https://www.netflix.com/title/80014749."
    assert fake.sent == [("key", "DPAD_UP"), ("key", "DPAD_CENTER"),
                         ("launch", "https://www.disneyplus.com"), ("launch", "https://www.netflix.com/title/80014749")]
    assert g.status()["device"] == "TOPTRO TP3"


def test_set_volume_uses_the_device_scale(gtv):
    g, fake = gtv
    fake.volume_info = {"level": 2, "max": 15, "muted": False}
    assert g.set_volume(10) == "Volume set to 10 (of 15)."
    assert fake.sent == [("key", "VOLUME_UP")] * 8
    with pytest.raises(ValueError, match="0 to 15"):
        g.set_volume(20)


def test_unpaired_is_explained(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))
    with pytest.raises(googletv.TVError, match="Not paired"):
        googletv.GoogleTV("10.0.0.6").press(["KEY_UP"])


def test_status_waits_for_late_volume_info(gtv, monkeypatch):
    g, fake = gtv
    fake.volume_info, fake.current_app = None, None
    real_sleep = googletv.asyncio.sleep

    async def sleep(t):
        fake.volume_info = {"level": 3, "max": 15, "muted": False}
        fake.current_app = "com.google.android.apps.tv.launcherx"
        await real_sleep(0)

    monkeypatch.setattr(googletv.asyncio, "sleep", sleep)
    st = g.status()
    assert st["volume"] == 3 and st["app"].endswith("launcherx")


def test_launch_falls_back_to_package_then_reports_failure(gtv, monkeypatch):
    g, fake = gtv
    monkeypatch.setattr(googletv.asyncio, "sleep", _instant)
    with pytest.raises(googletv.TVError, match="not showing"):
        g.launch("Stan")
    assert fake.sent == [("launch", "https://play.stan.com.au"), ("launch", "au.com.stan.and")]


async def _instant(_):
    pass


def test_launch_without_app_reporting_just_sends(gtv, monkeypatch):
    g, fake = gtv
    fake.current_app = None
    monkeypatch.setattr(googletv.asyncio, "sleep", _instant)
    assert "doesn't report" in g.launch("Stan")
    assert fake.sent == [("launch", "https://play.stan.com.au")]


class FakeGTV:
    """Foreground app follows launches and the Back -> Right -> OK exit."""

    def __init__(self):
        self.app = "com.google.android.apps.tv.launcherx"
        self.keys = []
        self.launched = []

    def press(self, keys, delay=0.3):
        self.keys += keys
        if keys == ["KEY_MENU"]:
            self.app = "com.android.tv.settings"
        return keys

    def launch(self, name):
        self.launched.append(name)
        if name.lower() == "netflix":
            self.app = "com.netflix.ninja"
        return f"Opened {name}."

    def foreground(self):
        return self.app


def test_netflix_on_google_tv_uses_its_own_exit_and_search_route(tmp_path, monkeypatch):
    from samsung_tv_mcp import netflix

    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(netflix.time, "sleep", lambda s: None)
    dev = googletv.GoogleTVDevice("10.0.0.7")
    fake = FakeGTV()
    dev.gtv = fake
    dev.dial = googletv._AppState(fake)
    msg = netflix.watch(dev, "Ben", "rick")
    assert "Ben" in msg
    k = fake.keys
    force_stop = (["KEY_MENU", "KEY_ENTER"] + ["KEY_DOWN"] * 4 + ["KEY_RIGHT", "KEY_DOWN", "KEY_ENTER"]
                  + ["KEY_DOWN", "KEY_ENTER", "KEY_ENTER"])
    n = len(force_stop)
    assert k[:n] == force_stop  # force-stop Netflix from Settings
    assert k[n:n + 8] == netflix.profile_keys(netflix.DEFAULT_PROFILES, "Ben")
    after = k[n + 8:]
    assert after[:3] == ["KEY_UP", "KEY_LEFT", "KEY_ENTER"]  # the projector's route to Search
    assert after[3:3 + len(netflix.type_keys("rick"))] == netflix.type_keys("rick")
    assert fake.launched == ["Netflix", "Netflix"]


def test_any_uri_scheme_is_sent_as_a_link(gtv):
    g, fake = gtv
    assert g.launch("package:com.netflix.ninja#Intent;end").startswith("Opened package:")
    assert fake.sent == [("launch", "package:com.netflix.ninja#Intent;end")]


def test_unlinked_youtube_picks_the_account_then_resends_the_video(tmp_path, monkeypatch):
    import time

    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    dev = googletv.GoogleTVDevice("10.0.0.7")
    fake = FakeGTV()
    dev.gtv = fake
    dev.dial = googletv._AppState(fake)
    msg = dev.play_youtube("https://www.youtube.com/watch?v=aqz-KE-bpKQ")
    link = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
    assert fake.launched == [link, link]  # again after "Who's watching?"
    assert fake.keys == ["KEY_ENTER"]
    assert "Link with TV code" in msg

    fake.launched, fake.keys = [], []
    fake.app = "com.google.android.youtube.tv"  # already open: no account picker
    dev.play_youtube("https://youtu.be/aqz-KE-bpKQ?t=30")
    assert fake.launched == [link + "&t=30s"] and fake.keys == []


def test_typing_keys_map_to_android_delete_and_enter():
    assert googletv.to_keycode("KEY_BACKSPACE") == "DEL"
    assert googletv.to_keycode("KEY_TEXT_ENTER") == "ENTER"


def test_keyboard_box_number_is_remembered_and_text_goes_there(gtv):
    import asyncio

    from androidtvremote2 import remote as rm
    from androidtvremote2.remotemessage_pb2 import RemoteMessage

    googletv._patch_keyboard_tracking()
    loop = asyncio.new_event_loop()
    proto = rm.RemoteProtocol(loop.create_future(), loop.create_future(), lambda *_: None, lambda *_: None,
                              lambda *_: None, loop, True, False)
    sent = []
    proto._send_message = sent.append
    show = RemoteMessage()
    show.remote_ime_show_request.remote_text_field_status.counter_field = 7
    proto._handle_message(show.SerializeToString())
    assert proto.ime_counter == 7 and proto.keyboard_seen

    g, fake = gtv
    fake._remote_message_protocol = proto
    assert g.set_text("rick") is True
    edit = sent[-1].remote_ime_batch_edit
    assert edit.ime_counter == 7 and edit.edit_info[0].text_field_status.value == "rick"
    assert edit.edit_info[0].text_field_status.start == 3
    g.set_text("")  # cleared on the phone: clear it on the projector too
    assert sent[-1].remote_ime_batch_edit.edit_info[0].text_field_status.value == ""
    loop.close()


def test_projector_sends_only_new_letters():
    class Gtv:
        def __init__(self):
            self.log = []

        def set_text(self, value):
            self.log.append(value)
            return True

        def press(self, keys, delay=0.3):
            self.log.append(tuple(keys))
            return keys

    proj = googletv.Projector.__new__(googletv.Projector)
    proj.gtv = Gtv()
    for text in ("h", "hi", "h", ""):
        proj.type_text(text)
    assert proj.gtv.log == ["h", "i", ("KEY_BACKSPACE",), ("KEY_BACKSPACE",)]


def test_keyboard_box_number_is_remembered_and_text_goes_there(gtv):
    import asyncio

    from androidtvremote2 import remote as rm
    from androidtvremote2.remotemessage_pb2 import RemoteMessage

    googletv._patch_keyboard_tracking()
    loop = asyncio.new_event_loop()
    proto = rm.RemoteProtocol(loop.create_future(), loop.create_future(), lambda *_: None, lambda *_: None,
                              lambda *_: None, loop, True, False)
    sent = []
    proto._send_message = sent.append
    show = RemoteMessage()
    show.remote_ime_show_request.remote_text_field_status.counter_field = 7
    proto._handle_message(show.SerializeToString())
    assert proto.ime_counter == 7 and proto.keyboard_seen

    g, fake = gtv
    fake._remote_message_protocol = proto
    assert g.set_text("rick") is True
    edit = sent[-1].remote_ime_batch_edit
    assert edit.ime_counter == 7 and edit.edit_info[0].text_field_status.value == "rick"
    assert edit.edit_info[0].text_field_status.start == 3
    g.set_text("")  # cleared on the phone: clear it on the projector too
    assert sent[-1].remote_ime_batch_edit.edit_info[0].text_field_status.value == ""
    loop.close()


def test_projector_sends_the_whole_box_each_time():
    class Gtv:
        def __init__(self):
            self.log = []

        def set_text(self, value):
            self.log.append(value)
            return True

    proj = googletv.Projector.__new__(googletv.Projector)
    proj.gtv = Gtv()
    for text in ("h", "hi", "h", ""):
        proj.type_text(text)
    assert proj.gtv.log == ["h", "hi", "h", ""]
