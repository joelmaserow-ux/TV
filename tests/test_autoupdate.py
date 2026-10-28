import json

from samsung_tv_mcp import autoupdate


class Dist:
    def __init__(self, data):
        self.data = data

    def read_text(self, name):
        return json.dumps(self.data)


def test_installed_reads_where_uv_got_it(monkeypatch):
    import importlib.metadata as md

    monkeypatch.setattr(md, "distribution", lambda name: Dist({
        "url": "https://github.com/joelmaserow-ux/TV",
        "vcs_info": {"vcs": "git", "requested_revision": "ccr-5fac4f84-5wt34a", "commit_id": "abc123"},
    }))
    assert autoupdate.installed() == ("joelmaserow-ux/TV", "ccr-5fac4f84-5wt34a", "abc123")
    monkeypatch.setattr(md, "distribution", lambda name: Dist({"url": "file:///home/user/TV", "dir_info": {}}))
    assert autoupdate.installed() is None


def test_only_runs_under_autostart(monkeypatch):
    monkeypatch.delenv("SAMSUNG_TV_AUTOUPDATE", raising=False)
    assert autoupdate.start(lambda: False) is False
