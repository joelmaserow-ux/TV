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


def test_short_query_stops_at_the_first_words_that_find_it(monkeypatch):
    asked = []

    def fake_search(query, limit=10):
        asked.append(query)
        top = {"rick": "Rick and Morty", "the": "The Crown", "the office": "The Office (US)"}
        return [{"title": top.get(query, "Something Else"), "year": 2013, "kind": "Show", "poster": ""}]

    monkeypatch.setattr(netflix_search, "search", fake_search)
    assert netflix_search.short_query("Rick and Morty") == "rick"
    assert asked == ["rick"]
    # "the" is too short to trust; "the office" brings up a different title, so type it all.
    asked.clear()
    assert netflix_search.short_query("The Office") == "the office"
    assert asked == []  # a single extra word is the whole title, nothing shorter to try


def test_short_query_falls_back_to_full_title_when_offline(monkeypatch):
    def boom(*a, **k):
        raise netflix_search.TVError("down")

    monkeypatch.setattr(netflix_search, "search", boom)
    assert netflix_search.short_query("Stranger Things") == "stranger things"


def test_netflix_seasons_counts_only_seasons_on_netflix(monkeypatch):
    nfx = {"package": {"shortName": "nfx", "clearName": "Netflix"}}
    stan = {"package": {"shortName": "stn", "clearName": "Stan"}}
    data = {"data": {"popularTitles": {"edges": [
        {"node": {"objectType": "MOVIE", "content": {"title": "Rick and Morty", "originalReleaseYear": 2013}}},
        {"node": {"objectType": "SHOW", "content": {"title": "Rick and Morty", "originalReleaseYear": 2013},
                  "seasons": [
                      {"content": {"seasonNumber": 0}, "offers": [nfx]},
                      {"content": {"seasonNumber": 2}, "offers": [nfx]},
                      {"content": {"seasonNumber": 1}, "offers": [stan, nfx]},
                      {"content": {"seasonNumber": 3}, "offers": [stan]},
                  ]}},
    ]}}}
    monkeypatch.setattr(netflix_search, "_post", lambda *a: data)
    assert netflix_search.netflix_seasons("Rick and Morty", 2013) == [1, 2]
    assert netflix_search.netflix_seasons("Other Show") is None
