import pytest

from samsung_tv_mcp import episodes
from samsung_tv_mcp.legacy import TVError


def fake_api(monkeypatch, responses):
    calls = []

    def get(path):
        calls.append(path)
        for prefix, value in responses.items():
            if path.startswith(prefix):
                return value
        raise AssertionError(path)

    monkeypatch.setattr(episodes, "_get", get)
    return calls


def test_seasons_groups_and_sorts_and_skips_specials(monkeypatch):
    calls = fake_api(monkeypatch, {
        "/search/shows": [
            {"show": {"id": 1, "name": "Rick and Morty Fan Show", "premiered": "2020-01-01"}},
            {"show": {"id": 216, "name": "Rick and Morty", "premiered": "2013-12-02"}},
        ],
        "/shows/216/episodes": [
            {"season": 2, "number": 1, "name": "A Rickle in Time", "image": {"medium": "http://x/2-1.jpg"}, "runtime": 22},
            {"season": 1, "number": 2, "name": "Lawnmower Dog", "image": None, "summary": "<p>Dog <b>smart</b></p>"},
            {"season": 1, "number": 1, "name": "Pilot", "image": {"medium": "https://x/1-1.jpg"}},
            {"season": 1, "number": None, "name": "Special"},
        ],
    })
    data = episodes.seasons("Rick and Morty", 2013)
    assert "q=Rick+and+Morty" in calls[0]
    assert data["show"] == "Rick and Morty"
    assert [s["number"] for s in data["seasons"]] == [1, 2]
    s1 = data["seasons"][0]["episodes"]
    assert [e["number"] for e in s1] == [1, 2] and s1[1]["summary"] == "Dog smart"
    assert data["seasons"][1]["episodes"][0]["image"] == "https://x/2-1.jpg"


def test_prefers_exact_name_without_year(monkeypatch):
    fake_api(monkeypatch, {
        "/search/shows": [{"show": {"id": 1, "name": "Ricky"}}, {"show": {"id": 2, "name": "rick and morty"}}],
        "/shows/2/episodes": [{"season": 1, "number": 1, "name": "Pilot"}],
    })
    assert episodes.seasons("Rick and Morty")["seasons"][0]["episodes"][0]["name"] == "Pilot"


def test_no_show_found(monkeypatch):
    fake_api(monkeypatch, {"/search/shows": []})
    with pytest.raises(TVError, match="still tap Play"):
        episodes.seasons("Nope")
