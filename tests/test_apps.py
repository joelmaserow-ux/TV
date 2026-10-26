from samsung_tv_mcp import apps
from samsung_tv_mcp.legacy import TVError


class FakeDial:
    def status(self, name):
        if name == "Plex":
            raise TVError("timeout")
        return {"YouTube": "running", "Netflix": "stopped", "ABCiview": "stopped"}.get(name, "not available")


def test_find_apps_keeps_installed_in_order():
    assert apps.find_apps(FakeDial()) == [
        {"id": "YouTube", "name": "YouTube"},
        {"id": "Netflix", "name": "Netflix"},
        {"id": "ABCiview", "name": "ABC iview"},
    ]
