"""Interactive check of every family-remote button against the real TV."""

from __future__ import annotations

import time
from typing import Callable

from . import keymap, youtube
from .legacy import TVError
from .text_input import type_text
from .tv import TV

APPS = ("YouTube", "Netflix")
TEST_VIDEO = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"  # Big Buck Bunny, 10 minutes


def _start_test_video(tv: TV, ask, say) -> None:
    """Get a video playing for the playback buttons, without relying on anyone opening YouTube."""
    if youtube.is_linked(tv.s.host):
        say("\n>> Starting a test video on the TV (this can take up to 40 seconds)...")
        try:
            say("   " + tv.play_youtube(TEST_VIDEO))
        except TVError as exc:
            say(f"   Couldn't start it: {exc}")
        if _yes_no(ask, "   Is a video playing on the TV now?") == "y":
            return
    say("\n>> Start any YouTube video on the TV with the TV remote and let it play.")
    say("   If YouTube won't load, answer s to each playback button and retest them later.")
    ask("   Press Enter when it's playing.")


def _yes_no(ask: Callable[[str], str], question: str) -> str:
    while True:
        answer = ask(f"{question} [y = yes, n = no, s = skip] ").strip().lower()[:1]
        if answer in ("y", "n", "s"):
            return answer


def _test_typing(tv: TV, data: dict, ask, say) -> None:
    say("\n>> Typing: open YouTube on the TV and go to its Search screen (the on-screen keyboard).")
    if _yes_no(ask, "   Is the search keyboard showing?") != "y":
        say("   Skipped typing. Retest later with: samsung-tv button-test typing")
        return
    try:
        type_text(tv.s.host, "abc")
        data["typing"] = _yes_no(ask, "[Type] Did 'abc' appear in the search box?") == "y"
    except TVError as exc:
        say(f"   {exc}")
        data["typing"] = False
    say("   Typing: " + ("works" if data["typing"] else "not supported, the box will be hidden"))
    keymap.save(tv.s.host, data)


def run(tv: TV, ask: Callable[[str], str] = input, say: Callable[[str], None] = print,
        only: list[str] | None = None) -> dict:
    data = keymap.load(tv.s.host)
    keys = data.setdefault("keys", {})
    say("Button test: I'll press each remote button on the TV and ask what happened.")
    say("Answer y if the TV did it, n if nothing happened, s to skip a button for now.\n")

    wanted = {o.lower() for o in only or []}
    test_typing = not only or bool(wanted & {"type", "typing"})
    for button in keymap.BUTTONS:
        if only and button.key.lower() not in wanted and button.label.lower() not in wanted:
            continue
        if button.setup == "PLAY_VIDEO":
            _start_test_video(tv, ask, say)
        elif button.setup:
            say(f"\n>> {button.setup}")
            ask("   Press Enter when ready.")
        result: str | None = None
        skipped = False
        for code in button.candidates:
            try:
                tv.remote.send_keys([code])
            except TVError as exc:
                say(f"   Couldn't send {code}: {exc}")
                continue
            time.sleep(0.8)
            answer = _yes_no(ask, f"[{button.label}] Did {button.expect}?")
            if answer == "y":
                result = code
                break
            if answer == "s":
                skipped = True
                break
            if code != button.candidates[-1]:
                say("   Trying another code for the same button...")
        if skipped:
            say(f"   Skipped {button.label}.")
            continue
        keys[button.key] = result
        say(f"   {button.label}: " + (f"works ({result})" if result else "not supported, it will be hidden"))
        keymap.save(tv.s.host, data)

    if only and not test_typing:
        pass
    elif only:
        _test_typing(tv, data, ask, say)
    else:
        apps = data.setdefault("apps", {})
        for app in APPS:
            try:
                available = tv.dial.status(app) != "not available"
            except TVError:
                available = False
            apps[app] = available
            say(f"\n{app} button: " + ("works" if available else "this TV can't open it directly, it will be hidden"))

        _test_typing(tv, data, ask, say)

    bad = [b.label for b in keymap.BUTTONS if keys.get(b.key, "untested") is None]
    say("\nDone. Saved for the remote and Claude.")
    if bad:
        say("Hidden because the TV doesn't respond: " + ", ".join(bad))
    say("Restart `samsung-tv remote` and reload the page on each phone to see the changes.")
    return data
