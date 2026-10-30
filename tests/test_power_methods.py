from samsung_tv_mcp import power_methods as pm
from samsung_tv_mcp.legacy import TVUnreachable


class Gtv:
    def __init__(self, reachable_when_off=True):
        self.sent = []
        self.on = True
        self.reachable_when_off = reachable_when_off

    def send_key(self, key, hold=False, fresh=False):
        if not self.on and not self.reachable_when_off:
            raise TVUnreachable("off")
        self.sent.append((key, hold))


class Device:
    def __init__(self, gtv):
        self.gtv = gtv
        self.s = type("S", (), {"host": "10.0.0.8"})()


def _quiet(monkeypatch, tmp_path):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(pm.time, "sleep", lambda s: None)


def test_finds_and_saves_off_then_on(tmp_path, monkeypatch):
    _quiet(monkeypatch, tmp_path)
    g = Gtv()
    # sleep: no; power: yes (off). On: wakeup no, power yes.
    answers = iter(["", "n", "", "y", "n", "", "y"])
    found = pm.run(Device(g), ask=lambda q: next(answers), say=lambda m: None)
    assert found == {"off": "power", "on": "power"}
    assert g.sent == [("SLEEP", False), ("POWER", False), ("WAKEUP", False), ("POWER", False)]
    assert pm.saved("10.0.0.8") == {"off": "power", "on": "power"}
    assert not any(hold for _, hold in g.sent)  # never a held key (that shuts Android down)


def test_says_so_when_it_drops_off_the_network(tmp_path, monkeypatch):
    _quiet(monkeypatch, tmp_path)
    g = Gtv(reachable_when_off=False)
    answers = iter(["", "y", "n"])  # sleep turns it off; then don't wait
    real = g.send_key

    def send_key(key, hold=False, fresh=False):
        real(key, hold, fresh)
        if key == "SLEEP":
            g.on = False

    g.send_key = send_key
    found = pm.run(Device(g), ask=lambda q: next(answers), say=lambda m: None)
    assert found == {"off": "sleep", "on": None}
    assert pm.saved("10.0.0.8") == {"off": "sleep", "on": "none"}


def test_defaults():
    assert pm.saved("10.9.9.1") == {"off": pm.DEFAULT_OFF, "on": pm.DEFAULT_ON}


def test_no_way_found_makes_the_power_button_explain(tmp_path, monkeypatch):
    import pytest

    from samsung_tv_mcp import googletv
    from samsung_tv_mcp.legacy import TVError

    _quiet(monkeypatch, tmp_path)
    g = Gtv()
    answers = iter(["", "n"] * len(pm.OFF))
    assert pm.run(Device(g), ask=lambda q: next(answers), say=lambda m: None) == {"off": None, "on": None}
    proj = googletv.Projector.__new__(googletv.Projector)
    proj.gtv, proj.s = g, type("S", (), {"host": "10.0.0.8"})()
    sent = len(g.sent)
    for action in (proj.power_off, proj.power_on):
        with pytest.raises(TVError, match="own remote"):
            action()
    assert len(g.sent) == sent  # nothing sent: no more restarting the stick


def test_turning_off_confirms_the_shut_down_question(tmp_path, monkeypatch):
    import time

    from samsung_tv_mcp import googletv

    _quiet(monkeypatch, tmp_path)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    g = Gtv()
    proj = googletv.Projector.__new__(googletv.Projector)
    proj.gtv, proj.s = g, type("S", (), {"host": "10.0.0.8"})()
    pm.save("10.0.0.8", off="power", on="none")
    proj.power_off()
    assert g.sent == [("POWER", False), ("DPAD_CENTER", False)]  # power, then OK on "shut down?"
