"""Ways of typing into a Google TV's text box, and a yes/no test to find the one that works.

Devices disagree on what a keyboard edit means: some take the whole box, some insert what
they're sent, some want the cursor after the text. `samsung-tv gtv typetest` types "hi"
each way and asks which came out right, then saves that one for the family remote.
"""

from __future__ import annotations

import json
import time

from .encrypted import credentials_path

DELETE = "KEY_BACKSPACE"

# name -> (what each change sends, the cursor it quotes, counter_offset, field_from_counter)
#   "new":  only the letters added since last time;  "full": the whole box
#   cursor "last": len(sent) - 1;  "after": len(whole box);  "after_sent": len(sent)
METHODS = {
    "new-after": ("new", "after", 0, False),
    "full-after": ("full", "after", 0, False),
    "new-after-sent": ("new", "after_sent", 0, False),
    "new-next": ("new", "last", 1, False),
    "full-next": ("full", "last", 1, False),
    "full-box": ("full", "last", 0, True),
    "new-box": ("new", "after", 0, True),
    "keys": ("keys", "", 0, False),
    "new-last": ("new", "last", 0, False),
}
DEFAULT = "new-after"


def _path(host: str):
    return credentials_path(host).with_name(f"{host}.typing.json")


def load(host: str) -> str:
    try:
        name = json.loads(_path(host).read_text()).get("method")
    except (OSError, ValueError):
        name = None
    return name if name in METHODS else DEFAULT


def save(host: str, name: str) -> None:
    path = _path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"method": name}))


def send(device, name: str, before: str, after: str) -> bool:
    """Change the box from `before` to `after` using method `name`."""
    what, cursor, offset, field = METHODS[name]
    same = 0
    while same < min(len(before), len(after)) and before[same] == after[same]:
        same += 1
    if len(before) > same:
        if what == "full":
            # The whole box goes anyway; deleting is just sending the shorter box.
            pass
        else:
            device.press([DELETE] * (len(before) - same), delay=0.05)
    added = after[same:]
    ok = True
    if what == "keys":
        codes = [{" ": "SPACE"}.get(ch, ch.upper()) for ch in added if ch.isalnum() or ch == " "]
        if codes:
            device.press(codes, delay=0.05)
        return True
    if what == "full":
        if added or len(before) > same:
            ok = device.gtv.ime_edit(after, start=_cursor(cursor, after, after), counter_offset=offset,
                                     field_from_counter=field)
        return ok
    typed = after[:same]
    for letter in added:  # one letter at a time
        typed += letter
        ok = device.gtv.ime_edit(letter, start=_cursor(cursor, letter, typed), counter_offset=offset,
                                 field_from_counter=field) and ok
    return ok


def _cursor(kind: str, sent: str, box: str) -> int:
    if kind == "after":
        return len(box)
    if kind == "after_sent":
        return len(sent)
    return len(sent) - 1


def run(device, ask=input, say=print) -> str | None:
    """Try each method on the projector and keep the first that types "hi" correctly."""
    say("Typing test. On the projector, open YouTube and select its search box so the keyboard shows.")
    ask("Press Enter when the projector's search keyboard is showing.")
    for i, name in enumerate(METHODS, 1):
        ask(f"\n[{i}/{len(METHODS)}] Clear the projector's search box (delete everything with its own remote),"
            " then press Enter here.")
        send(device, name, "", "h")
        time.sleep(1.0)
        send(device, name, "h", "hi")
        time.sleep(1.5)
        if _yes(ask, "Does the projector's box read exactly  hi  (two letters)?"):
            save(device.s.host, name)
            say(f"Saved: the remote will type this way ({name}).")
            send(device, name, "hi", "h")
            time.sleep(1.5)
            if _yes(ask, "Now does it read just  h  (the i deleted)?"):
                say("Deleting works too.")
            else:
                say("Typing works; deleting doesn't yet. Tell Claude: 'typing works, deleting doesn't'.")
            return name
    say("None of them typed hi correctly. Tell Claude: 'typing test: none worked'.")
    return None


def _yes(ask, question: str) -> bool:
    while True:
        answer = ask(f"{question} [y/n] ").strip().lower()[:1]
        if answer in ("y", "n"):
            return answer == "y"
