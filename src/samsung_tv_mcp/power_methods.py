"""Ways of turning a Google TV device off and on, and a yes/no test to find the ones that work.

Devices disagree: on the TOPTRO TP3 the plain power key restarts its streaming stick instead
of turning the projector off. `samsung-tv gtv --ip <ip> powertest` tries each way, asks
whether it worked, and saves the ones that did; the family remote's power button uses them.
"""

from __future__ import annotations

import json
import time

from .encrypted import credentials_path
from .legacy import TVError

# name -> (Android key, long press?)
# Never a held power key: on Android that's "shut down", which fully powers the stick off
# (on the TP3 it then sits on "GTV loading" while it starts again).
OFF = {
    "sleep": ("SLEEP", False),
    "power": ("POWER", False),
    "tv-power": ("TV_POWER", False),
}
ON = {
    "wakeup": ("WAKEUP", False),
    "power": ("POWER", False),
    "tv-power": ("TV_POWER", False),
}
DEFAULT_OFF = "power"
DEFAULT_ON = "wakeup"


def _path(host: str):
    return credentials_path(host).with_name(f"{host}.power.json")


def saved(host: str) -> dict:
    try:
        data = json.loads(_path(host).read_text())
    except (OSError, ValueError):
        data = {}
    # "none": the test found no way, so the power button explains instead of guessing.
    return {
        "off": data.get("off") if data.get("off") in (*OFF, "none") else DEFAULT_OFF,
        "on": data.get("on") if data.get("on") in (*ON, "none") else DEFAULT_ON,
    }


def save(host: str, **choice) -> None:
    data = saved(host) | {k: v for k, v in choice.items() if v}
    path = _path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def send(gtv, table: dict, name: str, fresh: bool = False) -> None:
    key, hold = table[name]
    gtv.send_key(key, hold=hold, fresh=fresh)


def run(device, ask=input, say=print) -> dict:
    """Find a way to turn it off, then a way to turn it back on."""
    gtv, host = device.gtv, device.s.host
    found = {"off": None, "on": None}
    say("Power test. Every step: watch the projector, then answer y or n.")
    for i, name in enumerate(OFF, 1):
        ask(f"\n[off {i}/{len(OFF)}] Make sure the projector is ON and showing the home screen, then press Enter.")
        try:
            send(gtv, OFF, name, fresh=True)
        except TVError as exc:
            say(f"  Couldn't send it: {exc}")
            continue
        time.sleep(8)
        if _yes(ask, "Did the projector turn OFF and stay off (not restart)?"):
            found["off"] = name
            break
    if not found["off"]:
        save(host, off="none", on="none")
        say("Nothing turned it off properly, so the remote's power button will now say to use the "
            "projector's own remote instead. Tell Claude: 'power test: no off worked'.")
        return found
    save(host, off=found["off"])
    say(f"Saved: off = {found['off']}.")

    for i, name in enumerate(ON, 1):
        say(f"\n[on {i}/{len(ON)}] Trying to turn it on...")
        try:
            send(gtv, ON, name, fresh=True)
        except TVError:
            say("  The projector isn't answering on the network while it's off.")
            if _yes(ask, "Wait 30 seconds and try that again? (n = give up on turning it on remotely)"):
                time.sleep(30)
                try:
                    send(gtv, ON, name, fresh=True)
                except TVError:
                    say("  Still not answering: it switches its network off when it's off.")
                    break
            else:
                break
        time.sleep(10)
        if _yes(ask, "Did the projector turn ON?"):
            found["on"] = name
            save(host, on=name)
            say(f"Saved: on = {name}.")
            break
        ask("Leave it off (turn it off again with its own remote if it came on oddly), then press Enter.")
    say(f"\nPower test: off = {found['off'] or 'none'}, on = {found['on'] or 'none'}. Tell Claude this line.")
    return found


def _yes(ask, question: str) -> bool:
    while True:
        answer = ask(f"{question} [y/n] ").strip().lower()[:1]
        if answer in ("y", "n"):
            return answer == "y"
