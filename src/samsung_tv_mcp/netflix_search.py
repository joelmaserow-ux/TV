"""Find Netflix shows and movies with posters, so the remote can show what you're picking.

Netflix has no public search API, so this asks JustWatch (a free guide to what's on each
streaming service per country) for titles on Netflix. It's an unofficial use of their API and
may change; if it fails, the remote still lets you type a name and watch.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .legacy import TVError

API = "https://apis.justwatch.com/graphql"
IMAGES = "https://images.justwatch.com"
QUERY = """
query GetSearchTitles($searchTitlesFilter: TitleFilter!, $country: Country!, $language: Language!, $first: Int!) {
  popularTitles(country: $country, filter: $searchTitlesFilter, first: $first, sortBy: POPULAR, sortRandomSeed: 0) {
    edges {
      node {
        objectType
        content(country: $country, language: $language) {
          title
          originalReleaseYear
          posterUrl
        }
      }
    }
  }
}
"""


def country() -> str:
    # The UA55H6300 is an Australian model; override with SAMSUNG_TV_COUNTRY (e.g. NZ, GB, US).
    return os.environ.get("SAMSUNG_TV_COUNTRY", "AU").strip().upper()


def poster(path: str | None) -> str:
    if not path:
        return ""
    return IMAGES + path.replace("{profile}", "s332").replace("{format}", "jpg")


def _post(operation: str, query: str, variables: dict) -> dict:
    body = json.dumps({"operationName": operation, "query": query, "variables": variables}).encode()
    req = urllib.request.Request(API, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (samsung-tv-mcp family remote)",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise TVError(f"Couldn't search Netflix's catalogue ({exc}). You can still type the name and tap Watch.") from exc
    if data.get("errors"):
        raise TVError(f"Netflix catalogue search failed: {data['errors'][0].get('message', data['errors'])}")
    return data


def _filter(query: str) -> dict:
    return {"searchQuery": query, "packages": ["nfx"]}


def search(query: str, limit: int = 10) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    data = _post("GetSearchTitles", QUERY, {
        "first": max(1, min(limit, 20)),
        "searchTitlesFilter": _filter(query),
        "country": country(),
        "language": "en",
    })
    results = []
    edges = (((data.get("data") or {}).get("popularTitles") or {}).get("edges")) or []
    for edge in edges:
        node = edge.get("node") or {}
        content = node.get("content") or {}
        title = content.get("title")
        if not title:
            continue
        results.append({
            "title": title,
            "year": content.get("originalReleaseYear") or "",
            "kind": "Show" if node.get("objectType") == "SHOW" else "Movie",
            "poster": poster(content.get("posterUrl")),
        })
    return results


def _same(a: str, b: str) -> bool:
    from .netflix import normalize_title

    return normalize_title(a) == normalize_title(b)


def short_query(title: str, year=None) -> str:
    """The fewest leading words of `title` that already bring it up first on Netflix.

    Typing on the TV keyboard is the slow part, so "rick and morty" becomes "rick" when that
    alone finds it. Netflix's own ranking isn't public; JustWatch's popularity order for the
    same words is a close stand-in, and anything shorter than 4 letters is never trusted.
    Falls back to the whole title if the check can't be made.
    """
    from .netflix import normalize_title

    full = normalize_title(title)
    words = full.split()
    for n in range(1, len(words)):
        prefix = " ".join(words[:n])
        if len(prefix.replace(" ", "")) < 4:
            continue
        try:
            hits = search(prefix, limit=2)
        except TVError:
            return full
        if hits and _same(hits[0]["title"], title) and (not year or str(hits[0]["year"]) == str(year)):
            return prefix
    return full


SEASONS_QUERY = """
query GetNetflixSeasons($searchTitlesFilter: TitleFilter!, $country: Country!, $language: Language!) {
  popularTitles(country: $country, filter: $searchTitlesFilter, first: 5, sortBy: POPULAR, sortRandomSeed: 0) {
    edges {
      node {
        objectType
        content(country: $country, language: $language) { title originalReleaseYear }
        ... on Show {
          seasons {
            content(country: $country, language: $language) { seasonNumber }
            offers(country: $country, platform: WEB) { package { shortName clearName } }
          }
        }
      }
    }
  }
}
"""


def netflix_seasons(title: str, year=None) -> list[int] | None:
    """Season numbers Netflix carries for `title` in this country, oldest first (None if unknown)."""
    try:
        data = _post("GetNetflixSeasons", SEASONS_QUERY, {
            "searchTitlesFilter": _filter(title), "country": country(), "language": "en",
        })
    except TVError:
        return None
    edges = (((data.get("data") or {}).get("popularTitles") or {}).get("edges")) or []
    for edge in edges:
        node = edge.get("node") or {}
        content = node.get("content") or {}
        if node.get("objectType") != "SHOW" or not _same(content.get("title") or "", title):
            continue
        if year and str(content.get("originalReleaseYear") or "") not in ("", str(year)):
            continue
        numbers = []
        for season in node.get("seasons") or []:
            number = ((season.get("content") or {}).get("seasonNumber"))
            on_netflix = any(
                (o.get("package") or {}).get("shortName") == "nfx"
                or ((o.get("package") or {}).get("clearName") or "").startswith("Netflix")
                for o in season.get("offers") or []
            )
            if number and number > 0 and on_netflix:
                numbers.append(int(number))
        return sorted(set(numbers)) or None
    return None
