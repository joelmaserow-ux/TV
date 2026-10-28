"""Ways of typing into a Google TV's text box, and yes/no tests to find the ones that work.

Devices, and even apps on one device, disagree on what a keyboard edit means: some take the
whole box, some insert what they're sent, some want the cursor after the text. The tests
(`samsung-tv gtv typetest`) type into whatever search box is open, ask whether it came out
right, and save what works for the app that's open, so YouTube, Netflix and the Google TV
home screen can each type their own way.
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
DEFAULT = "new-after-sent"  # what the TOPTRO TP3 takes in YouTube and Netflix

# Ways of deleting letters (and clearing) when the typing method doesn't send the whole box.
#   "key": the Delete key;  "fwd-key": Android's forward-delete key
#   "box-after"/"box-last": send the shorter box, cursor after / on its last letter
#   "range": replace the removed letters with nothing;  "range-back": the same, end first
DELETES = ["key", "box-after", "box-last", "range", "range-back", "fwd-key"]
DEFAULT_DELETE = "key"  # the TP3's Delete key works

FRIENDLY = {
    "com.google.android.youtube.tv": "YouTube",
    "com.netflix.ninja": "Netflix",
    "com.google.android.apps.tv.launcherx": "the Google TV home screen",
    "com.google.android.katniss": "Google TV search",
}


# --- saved settings ---------------------------------------------------------------------------

def _path(host: str):
    return credentials_path(host).with_name(f"{host}.typing.json")


def _saved(host: str) -> dict:
    try:
        data = json.loads(_path(host).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def settings(host: str, app: str | None = None) -> dict:
    """How to type in `app` on this device: {"method", "delete", "chunk"}.

    The app's own results win, then the device-wide ones, then the defaults.
    """
    data = _saved(host)
    merged = {"method": DEFAULT, "delete": DEFAULT_DELETE, "chunk": False}
    for layer in (data, (data.get("apps") or {}).get(app or "", {})):
        if layer.get("method") in METHODS:
            merged["method"] = layer["method"]
        if layer.get("delete") in DELETES:
            merged["delete"] = layer["delete"]
        if isinstance(layer.get("chunk"), bool):
            merged["chunk"] = layer["chunk"]
    return merged


def load(host: str, app: str | None = None) -> str:
    return settings(host, app)["method"]


def load_delete(host: str, app: str | None = None) -> str:
    return settings(host, app)["delete"]


def save(host: str, name: str | None = None, delete: str | None = None, app: str | None = None,
         chunk: bool | None = None) -> None:
    data = _saved(host)
    layer = data.setdefault("apps", {}).setdefault(app, {}) if app else data
    if name:
        layer["method"] = name
    if delete:
        layer["delete"] = delete
    if chunk is not None:
        layer["chunk"] = chunk
    path = _path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1))


def app_name(app: str | None) -> str:
    if not app:
        return "this app"
    return FRIENDLY.get(app, app)


# --- typing -----------------------------------------------------------------------------------

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


def send(device, name: str, before: str, after: str, delete: str | None = None, chunk: bool = False) -> bool:
    """Change the box from `before` to `after` using method `name` (and `delete` to remove).

    With `chunk`, letters added together go in one edit instead of one edit per letter,
    which is quicker in apps that refresh their results after every edit (like Netflix).
    """
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
    pieces = [added] if chunk and added else list(added)
    for piece in pieces:
        typed += piece
        ok = device.gtv.ime_edit(piece, start=_cursor(cursor, piece, typed), counter_offset=offset,
                                 field_from_counter=field) and ok
    return ok


def _cursor(kind: str, sent: str, box: str) -> int:
    if kind == "after":
        return len(box)
    if kind == "after_sent":
        return len(sent)
    return len(sent) - 1


# --- the yes/no tests -------------------------------------------------------------------------

def _foreground(device) -> str | None:
    try:
        return device.gtv.foreground()
    except Exception:
        return None


def _open_keyboard(device, ask, say) -> str | None:
    """Connect first, then have the keyboard opened, so the device is ready. Returns the app."""
    try:
        device.gtv.status()
    except Exception as exc:  # shown, but the test can still try
        say(f"(Couldn't reach the projector yet: {exc})")
    ask("On the projector, open the search box you want to test (YouTube, Netflix or the home "
        "screen's search) so its keyboard shows. Then press Enter here.")
    app = _foreground(device)
    say(f"Testing typing in {app_name(app)}.")
    return app


def _clear(ask) -> None:
    ask("Clear the projector's search box with its own remote, then press Enter here.")


def run(device, ask=input, say=print, app: str | None = None, opened: bool = False) -> str | None:
    """Try each typing method and keep the first that types "hi" correctly (for the open app)."""
    say("Typing test.")
    if not opened:
        app = _open_keyboard(device, ask, say)
    for i, name in enumerate(METHODS, 1):
        say(f"\n[{i}/{len(METHODS)}]")
        _clear(ask)
        send(device, name, "", "h")
        time.sleep(1.0)
        send(device, name, "h", "hi")
        time.sleep(1.5)
        if _yes(ask, "Does the projector's box read exactly  hi  (two letters)?"):
            save(device.s.host, name, app=app)
            say(f"Saved for {app_name(app)}: typing works ({name}).")
            return name
    say(f"None of them typed hi correctly in {app_name(app)}. Tell Claude: 'typing test: none worked'.")
    return None


def run_delete(device, ask=input, say=print, app: str | None = None, opened: bool = False) -> str | None:
    """Try each way of deleting and keep the first that works (then check Clear), for the open app."""
    host = device.s.host
    if not opened:
        app = _open_keyboard(device, ask, say)
    method = load(host, app)
    say(f"Deleting test ({app_name(app)}, typing: {method}).")
    if METHODS[method][0] == "full":
        say("It sends the whole box, so deleting and Clear work the same way as typing. Nothing to test.")
        return None
    _clear(ask)
    send(device, method, "", "h")
    time.sleep(1.0)
    send(device, method, "h", "hi")
    time.sleep(1.5)
    if not _yes(ask, "Does the projector's box read  hi ?"):
        say("Typing isn't working right here; run the typing test again first.")
        return None
    for i, how in enumerate(DELETES, 1):
        say(f"\n[{i}/{len(DELETES)}] Deleting the last letter...")
        remove(device, how, "hi", "h")
        time.sleep(1.5)
        if not _yes(ask, "Did the last letter disappear (box reads  h )?"):
            continue
        save(host, delete=how, app=app)
        say(f"Saved for {app_name(app)}: deleting works ({how}). Now checking Clear...")
        send(device, method, "h", "hi", how)
        time.sleep(1.5)
        remove(device, how, "hi", "")
        time.sleep(1.5)
        if _yes(ask, "Is the projector's box now empty?"):
            say(f"Deleting and Clear work in {app_name(app)}.")
        else:
            say(f"Deleting works but Clear didn't empty the box in {app_name(app)}. Tell Claude that.")
        return how
    say(f"No way of deleting worked in {app_name(app)}. Tell Claude: 'deleting test: none worked'.")
    return None


def run_fast(device, ask=input, say=print, app: str | None = None, opened: bool = False) -> bool:
    """Type like a phone does, through the remote's own path; then try quicker bursts of letters."""
    host = device.s.host
    if not opened:
        app = _open_keyboard(device, ask, say)
    chosen = settings(host, app)
    say(f"Fast typing test ({app_name(app)}, typing: {chosen['method']}, deleting: {chosen['delete']}).")
    save(host, app=app, chunk=False)
    _clear(ask)
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

    quick = False
    if typed:
        say("\nNow a quicker way: several letters in one go.")
        _clear(ask)
        save(host, app=app, chunk=True)
        device._typed = ""
        device.type_text("mr ")
        device.type_text("mr beast")
        time.sleep(1.5)
        quick = _yes(ask, "Does the box read exactly  mr beast ?")
        save(host, app=app, chunk=quick)
        device.type_text("")
        say("Quicker typing: " + ("on" if quick else "off (it stays letter by letter)") + f" for {app_name(app)}.")
    say(f"Fast test in {app_name(app)}: typing " + ("OK" if typed else "WRONG") + ", deleting "
        + ("OK" if deleted else "WRONG") + ", clear " + ("OK" if cleared else "WRONG")
        + ", quicker " + ("OK" if quick else "no") + ". Tell Claude this line.")
    return typed and deleted and cleared


def run_all(device, ask=input, say=print) -> None:
    """The whole check for one app's search box: typing, deleting and Clear, then speed."""
    app = _open_keyboard(device, ask, say)
    if run(device, ask, say, app=app, opened=True) is None:
        return
    run_delete(device, ask, say, app=app, opened=True)
    run_fast(device, ask, say, app=app, opened=True)


def _yes(ask, question: str) -> bool:
    while True:
        answer = ask(f"{question} [y/n] ").strip().lower()[:1]
        if answer in ("y", "n"):
            return answer == "y"
