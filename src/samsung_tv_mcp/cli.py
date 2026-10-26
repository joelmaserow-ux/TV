"""`samsung-tv` command: test the TV from a terminal before wiring up the MCP server."""

from __future__ import annotations

import argparse
import os
import sys

from .config import Settings
from .legacy import TVError
from .tv import TV


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="samsung-tv", description="Control a Samsung H-series TV.")
    p.add_argument("--host", help="TV IP address (default: $SAMSUNG_TV_HOST or 192.168.1.106)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("diagnose", help="probe the TV and test pairing")
    sub.add_parser("pair", help="PIN-pair with TVs that use encrypted firmware")
    sub.add_parser("status")
    sub.add_parser("off")
    sub.add_parser("on")
    sub.add_parser("volume", help="show volume").add_argument("level", nargs="?", type=int)
    sub.add_parser("louder").add_argument("steps", nargs="?", type=int, default=2)
    sub.add_parser("quieter").add_argument("steps", nargs="?", type=int, default=2)
    sub.add_parser("mute")
    sub.add_parser("key", help="press keys, e.g. KEY_MENU KEY_DOWN").add_argument("keys", nargs="+")
    app = sub.add_parser("app", help="open an app, e.g. YouTube")
    app.add_argument("name")
    app.add_argument("--params", default="", help="raw DIAL launch string, e.g. 'v=VIDEO_ID'")
    sub.add_parser("app-info", help="show what the TV reports about an app").add_argument("name")
    sub.add_parser("youtube", help="play a YouTube URL or id").add_argument("video")
    args = p.parse_args(argv)

    if args.host:
        os.environ["SAMSUNG_TV_HOST"] = args.host
    tv = TV(Settings.from_env())

    try:
        match args.cmd:
            case "diagnose":
                out = tv.diagnose()
            case "pair":
                print(tv.pair_start())
                print(tv.pair_finish(input("PIN shown on the TV: ")))
                out = tv.diagnose()
            case "status":
                out = tv.status()
            case "off":
                out = tv.power_off()
            case "on":
                out = tv.power_on()
            case "volume":
                out = tv.get_volume() if args.level is None else tv.set_volume(args.level)
            case "louder":
                out = tv.step_volume(args.steps)
            case "quieter":
                out = tv.step_volume(-args.steps)
            case "mute":
                out = tv.set_mute(None)
            case "key":
                out = "Pressed " + ", ".join(tv.remote.send_keys(args.keys))
            case "app":
                out = tv.open_app(args.name, args.params)
            case "app-info":
                out = "\n".join(tv.dial.raw(args.name))
            case "youtube":
                out = tv.play_youtube(args.video)
    except (TVError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
