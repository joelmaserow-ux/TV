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
