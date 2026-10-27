"""Find which apps this TV can open directly (over DIAL), so the remote shows only those."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .legacy import TVError
from .upnp import Dial

# DIAL names apps registered under on Samsung TVs of this era, with friendly labels. Only apps
# that support DIAL can be opened this way; anything else is reached through Smart Hub.
CANDIDATES: list[tuple[str, str]] = [
    ("YouTube", "YouTube"),
    ("Netflix", "Netflix"),
    ("AmazonInstantVideo", "Prime Video"),
    ("Plex", "Plex"),
    ("Spotify", "Spotify"),
    ("Hulu", "Hulu"),
    ("Pandora", "Pandora"),
    ("Twitch", "Twitch"),
    ("Dailymotion", "Dailymotion"),
    ("Vimeo", "Vimeo"),
    ("Crackle", "Crackle"),
    ("Vudu", "Vudu"),
    ("HBOGO", "HBO GO"),
    ("BBCiPlayer", "BBC iPlayer"),
    ("ABCiview", "ABC iview"),
    ("SBSOnDemand", "SBS On Demand"),
    ("Stan", "Stan"),
    ("9Now", "9Now"),
    ("7plus", "7plus"),
    ("10play", "10 play"),
    ("Foxtel", "Foxtel"),
    ("Kayo", "Kayo"),
    ("Binge", "Binge"),
    ("Facebook", "Facebook"),
]


def find_apps(dial: Dial) -> list[dict]:
    """Every candidate the TV reports as installed, in CANDIDATES order."""

    def probe(item: tuple[str, str]) -> dict | None:
        dial_id, label = item
        try:
            if dial.status(dial_id) != "not available":
                return {"id": dial_id, "name": label}
        except TVError:
            pass
        return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        found = list(pool.map(probe, CANDIDATES))
    seen, out = set(), []
    for item in found:
        if item and item["name"] not in seen:
            seen.add(item["name"])
            out.append(item)
    return out
