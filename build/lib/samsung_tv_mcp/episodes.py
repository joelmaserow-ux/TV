"""Season and episode lists with thumbnails, from TVmaze's free public API.

Netflix has no public episode list, so the remote shows TVmaze's. Netflix sometimes carries
fewer seasons in a country than exist; the remote says so rather than guessing.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .legacy import TVError

API = "https://api.tvmaze.com"


def _get(path: str):
    req = urllib.request.Request(API + path, headers={"User-Agent": "samsung-tv-mcp family remote"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise TVError(f"Couldn't load the episode list ({exc}). You can still tap Play.") from exc


def _strip_html(text: str | None) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def find_show(title: str, year: int | str | None = None) -> dict | None:
    hits = _get("/search/shows?" + urllib.parse.urlencode({"q": title})) or []
    shows = [h["show"] for h in hits if h.get("show")]
    if not shows:
        return None
    if year:
        for show in shows:
            if (show.get("premiered") or "")[:4] == str(year):
                return show
    wanted = title.strip().lower()
    return next((s for s in shows if (s.get("name") or "").lower() == wanted), shows[0])


def seasons(title: str, year: int | str | None = None) -> dict:
    """{"show": name, "seasons": [{"number": n, "episodes": [...]}, ...]}, oldest first."""
    show = find_show(title, year)
    if not show:
        raise TVError(f"Couldn't find episodes for {title}. You can still tap Play.")
    by_season: dict[int, list[dict]] = {}
    for ep in _get(f"/shows/{show['id']}/episodes") or []:
        season, number = ep.get("season"), ep.get("number")
        if not season or not number:  # specials have no episode number
            continue
        image = ep.get("image") or {}
        by_season.setdefault(int(season), []).append({
            "number": int(number),
            "name": ep.get("name") or f"Episode {number}",
            "image": (image.get("medium") or "").replace("http://", "https://"),
            "runtime": ep.get("runtime") or "",
            "summary": _strip_html(ep.get("summary"))[:200],
        })
    return {
        "show": show.get("name") or title,
        "seasons": [
            {"number": n, "episodes": sorted(eps, key=lambda e: e["number"])}
            for n, eps in sorted(by_season.items())
        ],
    }
