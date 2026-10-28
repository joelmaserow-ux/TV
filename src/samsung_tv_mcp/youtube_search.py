"""Search YouTube from the computer, so nobody has to type on the TV's on-screen keyboard."""

from __future__ import annotations

from .legacy import TVError


# YouTube's own "Type: Channel" search filter.
CHANNEL_FILTER = "EgIQAg%3D%3D"


def _extract(url: str, limit: int) -> dict:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise TVError("YouTube search needs the 'yt-dlp' package. Reinstall this project.") from exc
    options = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True,
               "playlistend": limit}
    try:
        with YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=False) or {}
    except Exception as exc:  # yt-dlp raises DownloadError and friends
        raise TVError(
            f"YouTube search failed ({exc}). If this keeps happening, run any samsung-tv command once "
            "with `uvx --refresh` to update the search library."
        ) from exc


def _videos(info: dict, channel: str = "") -> list[dict]:
    results = []
    for entry in info.get("entries") or []:
        video_id = entry.get("id")
        if not video_id or entry.get("ie_key") not in (None, "Youtube"):
            continue  # skip channels/playlists
        results.append({
            "id": video_id,
            "title": entry.get("title") or "(untitled)",
            "channel": entry.get("channel") or entry.get("uploader") or channel,
            "duration": format_duration(entry.get("duration")),
        })
    return results


def search(query: str, limit: int = 12) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    return _videos(_extract(f"ytsearch{max(1, min(limit, 25))}:{query}", limit))


def search_channels(query: str, limit: int = 4) -> list[dict]:
    """Channels matching `query`, best match first: id, name, subscribers, picture."""
    from urllib.parse import quote_plus

    query = query.strip()
    if not query:
        return []
    info = _extract(f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp={CHANNEL_FILTER}", limit)
    results = []
    for entry in info.get("entries") or []:
        channel_id = entry.get("channel_id") or entry.get("id") or ""
        if not channel_id.startswith("UC"):
            continue  # only real channels
        results.append({
            "id": channel_id,
            "name": entry.get("channel") or entry.get("title") or entry.get("uploader") or "(unnamed)",
            "subscribers": format_count(entry.get("channel_follower_count")),
            "thumbnail": _best_thumbnail(entry.get("thumbnails")),
        })
        if len(results) >= limit:
            break
    return results


def channel_videos(channel_id: str, limit: int = 30) -> list[dict]:
    """A channel's latest uploads, newest first."""
    channel_id = channel_id.strip()
    if not channel_id.startswith("UC") or not channel_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("That isn't a YouTube channel.")
    info = _extract(f"https://www.youtube.com/channel/{channel_id}/videos", limit)
    return _videos(info, info.get("channel") or info.get("uploader") or "")


def _best_thumbnail(thumbnails) -> str:
    urls = [t.get("url") for t in sorted(thumbnails or [], key=lambda t: t.get("width") or 0) if t.get("url")]
    if not urls:
        return ""
    url = urls[-1]
    return "https:" + url if url.startswith("//") else url


def format_count(n) -> str:
    if not n:
        return ""
    n = int(n)
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= size:
            value = f"{n / size:.1f}".rstrip("0").rstrip(".")
            return f"{value}{suffix} subscribers"
    return f"{n} subscribers"


def format_duration(seconds) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
