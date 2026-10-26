import io
import json

import pytest

from samsung_tv_mcp import netflix_search
from samsung_tv_mcp.legacy import TVError


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def test_search_sends_netflix_filter_and_parses(monkeypatch):
    sent = {}

    def fake_urlopen(req, timeout):
        sent["body"] = json.loads(req.data)
        return FakeResponse(json.dumps({"data": {"popularTitles": {"edges": [
            {"node": {"objectType": "SHOW", "content": {"title": "Rick and Morty", "originalReleaseYear": 2013,
                                                         "posterUrl": "/poster/123/{profile}/rick-and-morty.{format}"}}},
            {"node": {"objectType": "MOVIE", "content": {"title": "Rick", "originalReleaseYear": None, "posterUrl": None}}},
            {"node": {"content": {}}},
        ]}}}).encode())

    monkeypatch.setattr(netflix_search.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("SAMSUNG_TV_COUNTRY", "au")
    results = netflix_search.search("rick")
    v = sent["body"]["variables"]
    assert v["searchTitlesFilter"] == {"searchQuery": "rick", "packages": ["nfx"]} and v["country"] == "AU"
    assert results == [
        {"title": "Rick and Morty", "year": 2013, "kind": "Show",
         "poster": "https://images.justwatch.com/poster/123/s332/rick-and-morty.jpg"},
        {"title": "Rick", "year": "", "kind": "Movie", "poster": ""},
    ]


def test_search_reports_api_errors(monkeypatch):
    monkeypatch.setattr(netflix_search.urllib.request, "urlopen",
                        lambda req, timeout: FakeResponse(b'{"errors": [{"message": "bad query"}]}'))
    with pytest.raises(TVError, match="bad query"):
        netflix_search.search("rick")


def test_search_reports_network_errors(monkeypatch):
    def boom(req, timeout):
        raise OSError("no route")

    monkeypatch.setattr(netflix_search.urllib.request, "urlopen", boom)
    with pytest.raises(TVError, match="still type the name"):
        netflix_search.search("rick")
