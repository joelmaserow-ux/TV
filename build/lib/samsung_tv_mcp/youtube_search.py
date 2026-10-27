"""Search YouTube from the computer, so nobody has to type on the TV's on-screen keyboard."""

from __future__ import annotations

from .legacy import TVError


def search(query: str, limit: int = 12) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise TVError("YouTube search needs the 'yt-dlp' package. Reinstall this project.") from exc
    options = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(f"ytsearch{max(1, min(limit, 25))}:{query}", download=False)
    except Exception as exc:  # yt-dlp raises DownloadError and friends
        raise TVError(
            f"YouTube search failed ({exc}). If this keeps happening, run any samsung-tv command once "
            "with `uvx --refresh` to update the search library."
        ) from exc
    results = []
    for entry in (info or {}).get("entries") or []:
        video_id = entry.get("id")
        if not video_id or entry.get("ie_key") not in (None, "Youtube"):
            continue  # skip channels/playlists
        results.append({
            "id": video_id,
            "title": entry.get("title") or "(untitled)",
            "channel": entry.get("channel") or entry.get("uploader") or "",
            "duration": format_duration(entry.get("duration")),
        })
    return results


def format_duration(seconds) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
