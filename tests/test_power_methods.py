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
    # sleep: no; power: no; power-hold: yes (off). On: wakeup no, power yes.
    answers = iter(["", "n", "", "n", "", "y", "n", "", "y"])
    found = pm.run(Device(g), ask=lambda q: next(answers), say=lambda m: None)
    assert found == {"off": "power-hold", "on": "power"}
    assert g.sent == [("SLEEP", False), ("POWER", False), ("POWER", True), ("WAKEUP", False), ("POWER", False)]
    assert pm.saved("10.0.0.8") == {"off": "power-hold", "on": "power"}


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
    assert pm.saved("10.0.0.8")["off"] == "sleep"


def test_defaults():
    assert pm.saved("10.9.9.1") == {"off": pm.DEFAULT_OFF, "on": pm.DEFAULT_ON}
