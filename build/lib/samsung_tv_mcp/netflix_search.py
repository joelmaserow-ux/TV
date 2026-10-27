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


def search(query: str, limit: int = 10) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    body = json.dumps({
        "operationName": "GetSearchTitles",
        "query": QUERY,
        "variables": {
            "first": max(1, min(limit, 20)),
            "searchTitlesFilter": {"searchQuery": query, "packages": ["nfx"]},
            "country": country(),
            "language": "en",
        },
    }).encode()
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
