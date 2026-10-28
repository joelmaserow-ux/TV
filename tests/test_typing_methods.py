from samsung_tv_mcp import typing_methods as tm


class FakeGtv:
    def __init__(self):
        self.edits = []

    def status(self):
        return {"on": True}

    def ime_edit(self, value, start=None, end=None, counter_offset=0, field_from_counter=False):
        self.edits.append((value, start, counter_offset, field_from_counter))
        return True


class FakeDevice:
    def __init__(self):
        self.gtv = FakeGtv()
        self.pressed = []
        self.s = type("S", (), {"host": "10.0.0.9"})()

    def press(self, keys, delay=0.3):
        self.pressed += keys
        return keys


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


def test_typetest_saves_the_first_method_that_works(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(tm.time, "sleep", lambda s: None)
    answers = iter(["", "", "n", "", "y", "n"])  # the 2nd method types hi; deleting doesn't
    assert tm.run(FakeDevice(), ask=lambda q: next(answers), say=lambda m: None) == "full-after"
    assert tm.load("10.0.0.9") == "full-after"
    assert tm.load("10.0.0.10") == tm.DEFAULT


def test_delete_test_saves_the_way_that_works_and_checks_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(tm.time, "sleep", lambda s: None)
    tm.save("10.0.0.9", "new-after")
    d = FakeDevice()
    answers = iter(["", "y", "n", "y", "y"])  # box reads hi; Delete key no; shorter box yes; Clear yes
    assert tm.run_delete(d, ask=lambda q: next(answers), say=lambda m: None) == "box-after"
    assert tm.load("10.0.0.9") == "new-after" and tm.load_delete("10.0.0.9") == "box-after"
    assert d.pressed == ["KEY_BACKSPACE"]
    assert d.gtv.edits[-1] == ("", 0, 0, False)  # Clear: the empty box


def test_remove_ways():
    d = FakeDevice()
    tm.remove(d, "range", "hello", "he")
    tm.remove(d, "box-last", "hi", "h")
    assert d.gtv.edits == [("", 2, 0, False), ("h", 0, 0, False)]
