import pytest

from samsung_tv_mcp import episodes, netflix_search
from samsung_tv_mcp.legacy import TVError


@pytest.fixture(autouse=True)
def no_catalogue_lookups(monkeypatch, request):
    """Netflix routines look titles up online; tests run offline unless they fake it."""
    if request.module.__name__.endswith(("test_netflix_search", "test_episodes")):
        return

    def offline(*a, **k):
        raise TVError("offline")

    monkeypatch.setattr(netflix_search, "_post", offline)
    monkeypatch.setattr(episodes, "_get", offline)
