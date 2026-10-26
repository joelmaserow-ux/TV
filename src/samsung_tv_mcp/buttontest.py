"""Interactive check of every family-remote button against the real TV."""

from __future__ import annotations

import time
from typing import Callable

from . import keymap
from .legacy import TVError
from .text_input import type_text
from .tv import TV

APPS = ("YouTube", "Netflix")


def _yes_no(ask: Callable[[str], str], question: str) -> str:
    while True:
        answer = ask(f"{question} [y = yes, n = no, s = skip] ").strip().lower()[:1]
        if answer in ("y", "n", "s"):
            return answer


def run(tv: TV, ask: Callable[[str], str] = input, say: Callable[[str], None] = print,
        only: list[str] | None = None) -> dict:
    data = keymap.load(tv.s.host)
    keys = data.setdefault("keys", {})
    say("Button test: I'll press each remote button on the TV and ask what happened.")
    say("Answer y if the TV did it, n if nothing happened, s to skip a button for now.\n")

    for button in keymap.BUTTONS:
        if only and button.key not in only and button.label.lower() not in [o.lower() for o in only]:
            continue
        if button.setup:
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

    if not only:
        apps = data.setdefault("apps", {})
        for app in APPS:
            try:
                available = tv.dial.status(app) != "not available"
            except TVError:
                available = False
            apps[app] = available
            say(f"\n{app} button: " + ("works" if available else "this TV can't open it directly, it will be hidden"))

        say("\n>> Typing: open YouTube on the TV and go to its Search screen (the on-screen keyboard).")
        if _yes_no(ask, "   Is the search keyboard showing?") == "y":
            try:
                type_text(tv.s.host, "abc")
                data["typing"] = _yes_no(ask, "[Type] Did 'abc' appear in the search box?") == "y"
            except TVError as exc:
                say(f"   {exc}")
                data["typing"] = False
            say("   Typing: " + ("works" if data["typing"] else "not supported, the box will be hidden"))
        keymap.save(tv.s.host, data)

    bad = [b.label for b in keymap.BUTTONS if keys.get(b.key, "untested") is None]
    say("\nDone. Saved for the remote and Claude.")
    if bad:
        say("Hidden because the TV doesn't respond: " + ", ".join(bad))
    say("Restart `samsung-tv remote` and reload the page on each phone to see the changes.")
    return data
