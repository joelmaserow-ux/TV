from samsung_tv_mcp import typing_methods as tm


class FakeGtv:
    def __init__(self, app="com.google.android.youtube.tv"):
        self.edits = []
        self.app = app

    def status(self):
        return {"on": True}

    def foreground(self):
        return self.app

    def app_now(self):
        return self.app

    def ime_edit(self, value, start=None, end=None, counter_offset=0, field_from_counter=False):
        self.edits.append((value, start, counter_offset, field_from_counter))
        return True


class FakeDevice:
    def __init__(self, app="com.google.android.youtube.tv"):
        self.gtv = FakeGtv(app)
        self.pressed = []
        self.s = type("S", (), {"host": "10.0.0.9"})()
        self._typed = ""

    def press(self, keys, delay=0.3):
        self.pressed += keys
        return keys


def _quiet(monkeypatch, tmp_path):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(tm.time, "sleep", lambda s: None)


def test_methods_send_what_they_say():
    d = FakeDevice()
    tm.send(d, "new-after", "h", "hi")
    tm.send(d, "full-after", "h", "hi")
    tm.send(d, "new-last", "h", "hi")
    tm.send(d, "full-next", "h", "hi")
    assert d.gtv.edits == [("i", 2, 0, False), ("hi", 2, 0, False), ("i", 0, 0, False), ("hi", 1, 1, False)]
    tm.send(d, "keys", "", "hi there")
    assert d.pressed == ["H", "I", "SPACE", "T", "H", "E", "R", "E"]
    d.pressed.clear()
    tm.send(d, "new-after", "hi", "h")
    assert d.pressed == ["KEY_BACKSPACE"]
    d.gtv.edits.clear()
    tm.send(d, "full-after", "hi", "")  # the whole box goes, so clearing is an empty box
    assert d.gtv.edits == [("", 0, 0, False)]


def test_chunk_sends_added_letters_in_one_edit():
    d = FakeDevice()
    tm.send(d, "new-after-sent", "mr ", "mr beast", chunk=True)
    assert d.gtv.edits == [("beast", 5, 0, False)]
    d.gtv.edits.clear()
    tm.send(d, "new-after-sent", "mr ", "mr beast")
    assert [e[0] for e in d.gtv.edits] == list("beast")


def test_settings_are_per_app_with_device_wide_fallback(tmp_path, monkeypatch):
    _quiet(monkeypatch, tmp_path)
    home = "com.google.android.apps.tv.launcherx"
    assert tm.settings("10.0.0.9", home) == {"method": tm.DEFAULT, "delete": tm.DEFAULT_DELETE, "chunk": False}
    tm.save("10.0.0.9", "keys", app=home)
    tm.save("10.0.0.9", delete="range")
    tm.save("10.0.0.9", app="com.netflix.ninja", chunk=True)
    assert tm.settings("10.0.0.9", home) == {"method": "keys", "delete": "range", "chunk": False}
    assert tm.settings("10.0.0.9", "com.netflix.ninja") == {"method": tm.DEFAULT, "delete": "range", "chunk": True}


def test_typetest_saves_the_first_method_that_works_for_the_open_app(tmp_path, monkeypatch):
    _quiet(monkeypatch, tmp_path)
    home = "com.google.android.apps.tv.launcherx"
    answers = iter(["", "", "n", "", "y"])  # keyboard open; 1st method no; 2nd yes
    assert tm.run(FakeDevice(home), ask=lambda q: next(answers), say=lambda m: None) == "full-after"
    assert tm.load("10.0.0.9", home) == "full-after"
    assert tm.load("10.0.0.9", "com.netflix.ninja") == tm.DEFAULT  # other apps untouched


def test_delete_test_saves_the_way_that_works_and_checks_clear(tmp_path, monkeypatch):
    _quiet(monkeypatch, tmp_path)
    d = FakeDevice()
    answers = iter(["", "", "y", "n", "y", "y"])  # keyboard open, cleared; hi; key no; shorter box yes; Clear yes
    assert tm.run_delete(d, ask=lambda q: next(answers), say=lambda m: None) == "box-after"
    assert tm.load_delete("10.0.0.9", "com.google.android.youtube.tv") == "box-after"
    assert d.pressed == ["KEY_BACKSPACE"]
    assert d.gtv.edits[-1] == ("", 0, 0, False)  # Clear: the empty box


def test_remove_ways():
    d = FakeDevice()
    tm.remove(d, "range", "hello", "he")
    tm.remove(d, "box-last", "hi", "h")
    assert d.gtv.edits == [("", 2, 0, False), ("h", 0, 0, False)]


def test_fast_test_types_like_a_phone_then_tries_bursts(tmp_path, monkeypatch):
    _quiet(monkeypatch, tmp_path)
    d = FakeDevice("com.netflix.ninja")
    seen = []
    d.type_text = seen.append
    answers = iter(["", "", "y", "y", "y", "", "y"])
    assert tm.run_fast(d, ask=lambda q: next(answers), say=lambda m: None) is True
    assert seen[:3] == ["m", "mr", "mr "] and seen[7] == "mr beast" and seen[8:10] == ["mr bea", ""]
    assert seen[10:12] == ["mr ", "mr beast"]
    assert tm.settings("10.0.0.9", "com.netflix.ninja")["chunk"] is True
    assert tm.settings("10.0.0.9", "com.google.android.youtube.tv")["chunk"] is False
