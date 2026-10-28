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


# Ways of deleting letters (and clearing) when the typing method doesn't send the whole box.
#   "key": the Delete key;  "fwd-key": Android's forward-delete key
#   "box-after"/"box-last": send the shorter box, cursor after / on its last letter
#   "range": replace the removed letters with nothing;  "range-back": the same, end first
DELETES = ["key", "box-after", "box-last", "range", "range-back", "fwd-key"]
DEFAULT_DELETE = "key"


def _path(host: str):
    return credentials_path(host).with_name(f"{host}.typing.json")


def _saved(host: str) -> dict:
    try:
        data = json.loads(_path(host).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load(host: str) -> str:
    name = _saved(host).get("method")
    return name if name in METHODS else DEFAULT


def load_delete(host: str) -> str:
    name = _saved(host).get("delete")
    return name if name in DELETES else DEFAULT_DELETE


def save(host: str, name: str | None = None, delete: str | None = None) -> None:
    data = _saved(host)
    if name:
        data["method"] = name
    if delete:
        data["delete"] = delete
    path = _path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def remove(device, how: str, before: str, after: str) -> bool:
    """Delete from `before` down to `after` (a prefix of it) using deletion method `how`."""
    count = len(before) - len(after)
    if count <= 0:
        return True
    if how == "key":
        device.press([DELETE] * count, delay=0.05)
        return True
    if how == "fwd-key":
        device.press(["FORWARD_DEL"] * count, delay=0.05)
        return True
    if how == "box-after":
        return device.gtv.ime_edit(after, start=len(after))
    if how == "box-last":
        return device.gtv.ime_edit(after, start=len(after) - 1)
    if how == "range":
        return device.gtv.ime_edit("", start=len(after), end=len(before))
    return device.gtv.ime_edit("", start=len(before), end=len(after))  # range-back


def send(device, name: str, before: str, after: str, delete: str | None = None) -> bool:
    """Change the box from `before` to `after` using method `name` (and `delete` to remove)."""
    what, cursor, offset, field = METHODS[name]
    same = 0
    while same < min(len(before), len(after)) and before[same] == after[same]:
        same += 1
    if len(before) > same and what != "full":  # a whole box covers deleting by itself
        remove(device, delete or DEFAULT_DELETE, before, before[:same])
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
    say("Typing test.")
    _open_keyboard(device, ask, say)
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


def run_delete(device, ask=input, say=print) -> str | None:
    """Try each way of deleting on the projector and keep the first that works (then check Clear)."""
    host = device.s.host
    method = load(host)
    say(f"Typing method saved for this projector: {method}")
    if METHODS[method][0] == "full":
        say("It sends the whole box, so deleting and Clear work the same way as typing. Nothing to test.")
        return None
    say("Deleting test.")
    _open_keyboard(device, ask, say)
    ask("Clear the projector's search box with its own remote, then press Enter here.")
    send(device, method, "", "h")
    time.sleep(1.0)
    send(device, method, "h", "hi")
    time.sleep(1.5)
    if not _yes(ask, "Does the projector's box read  hi ?"):
        say("Typing isn't working right; run the typing test again first:  samsung-tv gtv --ip <ip> typetest")
        return None
    for i, how in enumerate(DELETES, 1):
        say(f"\n[{i}/{len(DELETES)}] Deleting the last letter...")
        remove(device, how, "hi", "h")
        time.sleep(1.5)
        if not _yes(ask, "Did the last letter disappear (box reads  h )?"):
            continue
        save(host, delete=how)
        say(f"Saved: the remote will delete this way ({how}). Now checking Clear...")
        send(device, method, "h", "hi", how)
        time.sleep(1.5)
        remove(device, how, "hi", "")
        time.sleep(1.5)
        if _yes(ask, "Is the projector's box now empty?"):
            say(f"Done. Typing: {method}. Deleting and Clear: {how}.")
        else:
            say(f"Done. Typing: {method}. Deleting: {how}, but Clear didn't empty the box. Tell Claude that.")
        return how
    say(f"No way of deleting worked. Typing: {method}. Tell Claude: 'deleting test: none worked'.")
    return None


def run_fast(device, ask=input, say=print) -> bool:
    """Type the way a phone does, letter by letter with no pauses, through the remote's own path."""
    say(f"Fast typing test (typing: {load(device.s.host)}, deleting: {load_delete(device.s.host)}).")
    _open_keyboard(device, ask, say)
    ask("Clear the projector's search box with its own remote, then press Enter here.")
    device._typed = ""
    text = ""
    for letter in "mr beast":
        text += letter
        device.type_text(text)
    time.sleep(1.5)
    typed = _yes(ask, "Does the projector's box read exactly  mr beast ?")
    device.type_text("mr bea")
    time.sleep(1.5)
    deleted = _yes(ask, "Did the last two letters go (box reads  mr bea )?")
    device.type_text("")
    time.sleep(1.5)
    cleared = _yes(ask, "Is the box empty now?")
    say("Fast test: typing " + ("OK" if typed else "WRONG") + ", deleting " + ("OK" if deleted else "WRONG")
        + ", clear " + ("OK" if cleared else "WRONG") + ". Tell Claude this line.")
    return typed and deleted and cleared


def _open_keyboard(device, ask, say) -> None:
    """Connect first, then have the keyboard opened, so its announcement reaches us."""
    try:
        device.gtv.status()
    except Exception as exc:  # shown, but the test can still try
        say(f"(Couldn't reach the projector yet: {exc})")
    ask("On the projector, open YouTube's search. If its keyboard is already showing, press Back "
        "and select the search box again so the keyboard pops up fresh. Then press Enter here.")


def _yes(ask, question: str) -> bool:
    while True:
        answer = ask(f"{question} [y/n] ").strip().lower()[:1]
        if answer in ("y", "n"):
            return answer == "y"
