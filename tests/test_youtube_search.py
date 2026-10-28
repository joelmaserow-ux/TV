import sys
import types

from samsung_tv_mcp import youtube_search


def test_search_parses_flat_entries(monkeypatch):
    seen = {}

    class FakeYDL:
        def __init__(self, opts):
            seen["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def extract_info(self, url, download):
            seen["url"] = url
            return {"entries": [
                {"id": "aqz-KE-bpKQ", "title": "Big Buck Bunny", "channel": "Blender", "duration": 634.0, "ie_key": "Youtube"},
                {"id": "UCxyz", "title": "A channel", "ie_key": "YoutubeTab"},
                {"id": "jNQXAC9IVRw", "title": "Me at the zoo", "uploader": "jawed", "duration": 19},
            ]}

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYDL))
    results = youtube_search.search("bunny", limit=5)
    assert seen["url"] == "ytsearch5:bunny" and seen["opts"]["extract_flat"] is True
    assert results == [
        {"id": "aqz-KE-bpKQ", "title": "Big Buck Bunny", "channel": "Blender", "duration": "10:34"},
        {"id": "jNQXAC9IVRw", "title": "Me at the zoo", "channel": "jawed", "duration": "0:19"},
    ]


def test_empty_query():
    assert youtube_search.search("  ") == []


def test_format_duration():
    assert youtube_search.format_duration(3725) == "1:02:05"
    assert youtube_search.format_duration(None) == ""


def _fake_ydl(monkeypatch, pages):
    seen = []

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def extract_info(self, url, download):
            seen.append((url, self.opts["playlistend"]))
            return pages[url.split("?")[0]]

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYDL))
    return seen


def test_channel_search_keeps_only_channels(monkeypatch):
    seen = _fake_ydl(monkeypatch, {"https://www.youtube.com/results": {"entries": [
        {"id": "UCX6OQ3DkcsbYNE6H8uQQuVA", "title": "MrBeast", "ie_key": "YoutubeTab",
         "channel_follower_count": 412_000_000,
         "thumbnails": [{"url": "//yt3.ggpht.com/small", "width": 88}, {"url": "//yt3.ggpht.com/big", "width": 176}]},
        {"id": "PLabc", "title": "A playlist", "ie_key": "YoutubeTab"},
        {"id": "UCbeast2", "channel": "Beast Reacts", "channel_follower_count": 950},
    ]}})
    results = youtube_search.search_channels("mr beast")
    assert seen[0][0] == "https://www.youtube.com/results?search_query=mr+beast&sp=EgIQAg%3D%3D"
    assert results == [
        {"id": "UCX6OQ3DkcsbYNE6H8uQQuVA", "name": "MrBeast", "subscribers": "412M subscribers",
         "thumbnail": "https://yt3.ggpht.com/big"},
        {"id": "UCbeast2", "name": "Beast Reacts", "subscribers": "950 subscribers", "thumbnail": ""},
    ]


def test_channel_videos_lists_uploads(monkeypatch):
    seen = _fake_ydl(monkeypatch, {"https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA/videos": {
        "channel": "MrBeast",
        "entries": [{"id": "abc123def45", "title": "I Survived 100 Days", "duration": 1500}],
    }})
    assert youtube_search.channel_videos("UCX6OQ3DkcsbYNE6H8uQQuVA") == [
        {"id": "abc123def45", "title": "I Survived 100 Days", "channel": "MrBeast", "duration": "25:00"}]
    assert seen[0][1] == 30


def test_channel_videos_refuses_anything_but_a_channel_id():
    import pytest

    for bad in ("", "PLabc", "UC../../x"):
        with pytest.raises(ValueError):
            youtube_search.channel_videos(bad)


def test_format_count():
    assert youtube_search.format_count(1_500_000) == "1.5M subscribers"
    assert youtube_search.format_count(2_000) == "2K subscribers"
    assert youtube_search.format_count(None) == ""
