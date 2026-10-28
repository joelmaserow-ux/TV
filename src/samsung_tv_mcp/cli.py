"""`samsung-tv` command: test the TV from a terminal before wiring up the MCP server."""

from __future__ import annotations

import argparse
import os
import sys

from .config import Settings
from .legacy import TVError
from .tv import TV


def _gtv(args) -> str:
    from .googletv import GoogleTV

    if not args.ip:
        raise ValueError("Give the Google TV's IP address with --ip (Settings > Network & Internet on it).")
    gtv = GoogleTV(args.ip)
    rest = " ".join(args.args)
    match args.command:
        case "pair":
            print(gtv.pair_start())
            return gtv.pair_finish(input("Code shown on the screen: "))
        case "status":
            return "\n".join(f"{k}: {v}" for k, v in gtv.status().items())
        case "key":
            return "Pressed " + ", ".join(gtv.press(args.args))
        case "app" | "link":
            return "Opened " + gtv.launch(rest)
        case "type":
            gtv.type_text(rest)
            return "Typed."
        case "volume":
            return gtv.set_volume(int(rest))
        case "power":
            return gtv.power({"on": True, "off": False}.get(rest.lower()) if rest else None)
    raise ValueError(args.command)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="samsung-tv", description="Control a Samsung H-series TV.")
    p.add_argument("-v", "--verbose", action="store_true", help="print protocol debug logs")
    p.add_argument("--gtv", metavar="IP",
                   help="run netflix/youtube/key/app commands on a Google TV (e.g. the projector) instead")
    p.add_argument("--host", help="TV IP address (default: $SAMSUNG_TV_HOST or 192.168.1.106)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("diagnose", help="probe the TV and test pairing")
    sub.add_parser("pair", help="PIN-pair with TVs that use encrypted firmware")
    rem = sub.add_parser("remote", help="run the family web remote for phones and laptops")
    rem.add_argument("--port", type=int, default=8765)
    rem.add_argument("--pin", help="set a new family PIN (otherwise the saved one is reused)")
    rem.add_argument("--projector", metavar="IP", help="also control a Google TV projector (remembered)")
    typ = sub.add_parser("type", help="type text into the TV's on-screen keyboard")
    typ.add_argument("text")
    typ.add_argument("--enter", action="store_true", help="also finish/submit the text")
    bt = sub.add_parser("button-test", help="check every remote button on the TV and remember what works")
    bt.add_argument("only", nargs="*", help="retest just these buttons, e.g. Off Pause")
    sub.add_parser("apps", help="list the apps this TV can open directly")
    nf = sub.add_parser("netflix", help="open Netflix as a profile, e.g. samsung-tv netflix Joel")
    nf.add_argument("profile")
    nf.add_argument("--wait", type=float, help="seconds Netflix needs to load before Exit (remembered)")
    nf.add_argument("--show", default="", help="search for this show/movie and open it")
    nf.add_argument("--play", action="store_true", help="with --show: press Continue/Start Watching")
    nf.add_argument("--from-start", action="store_true", help="with --show: play it from the beginning")
    nf.add_argument("--season", type=int, help="with --show: play this season...")
    nf.add_argument("--episode", type=int, help="...and this episode")
    nf.add_argument("--home-wait", type=float,
                    help="seconds after picking the profile before going to Search (remembered)")
    nf.add_argument("--profile-wait", type=float,
                    help="seconds after reopening before choosing the profile (remembered)")
    sub.add_parser("netflix-search", help="with Netflix's home screen showing, search and open a show").add_argument("show")
    sub.add_parser("netflix-find", help="look up Netflix shows (with posters) via JustWatch").add_argument("query")
    ep = sub.add_parser("netflix-episode", help="with a show's page open, play a season/episode")
    ep.add_argument("season", type=int)
    ep.add_argument("episode", type=int)
    sub.add_parser("episodes", help="list a series' seasons and episodes (TVmaze)").add_argument("show")
    sub.add_parser("netflix-close", help="fully quit Netflix so it reopens on the profile screen")
    sub.add_parser("netflix-profiles", help="set the profile names, top to bottom").add_argument("names", nargs="+")
    gtv = sub.add_parser("gtv", help="control a Google TV / Android TV (e.g. the projector)")
    gtv.add_argument("--ip", default=os.environ.get("GOOGLE_TV_HOST"), help="its IP address ($GOOGLE_TV_HOST)")
    gtv.add_argument("command", choices=["pair", "status", "key", "app", "link", "type", "volume", "power"])
    gtv.add_argument("args", nargs="*")
    sub.add_parser("install-claude", help="add this server to Claude Desktop's config").add_argument(
        "--config", help="path of the file Settings > Developer > Edit config opens (auto-detected if omitted)")
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
    sub.add_parser("youtube-link", help="link with the code from YouTube > Settings > Link with TV code").add_argument("code", nargs="+")
    args = p.parse_args(argv)

    if args.verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    if args.host:
        os.environ["SAMSUNG_TV_HOST"] = args.host
    tv = TV(Settings.from_env())
    if args.gtv:
        from .googletv import GoogleTVDevice

        supported = {"netflix", "netflix-close", "netflix-search", "netflix-episode", "youtube", "youtube-link",
                     "key", "app"}
        if args.cmd not in supported:
            print(f"Error: with --gtv, use one of: {', '.join(sorted(supported))} (or the gtv command).",
                  file=sys.stderr)
            return 1
        tv = GoogleTVDevice(args.gtv)

    try:
        match args.cmd:
            case "diagnose":
                out = tv.diagnose()
            case "pair":
                print(tv.pair_start())
                print(tv.pair_finish(input("PIN shown on the TV: ")))
                out = tv.diagnose()
            case "remote":
                from .webremote import serve
                serve(args.port, args.pin, args.projector)
                return 0
            case "type":
                from .text_input import type_text
                type_text(tv.s.host, args.text, args.enter)
                out = "Typed."
            case "button-test":
                from .buttontest import run as run_test
                run_test(tv, only=args.only or None)
                return 0
            case "apps":
                from .apps import find_apps
                found = find_apps(tv.dial)
                out = "\n".join(f"{a['name']}  (samsung-tv app {a['id']})" for a in found) or "None found."
            case "netflix":
                from . import netflix
                if args.wait or args.profile_wait or args.home_wait:
                    data = netflix.load(tv.s.host)
                    if args.wait:
                        data["startup_wait"] = args.wait
                    if args.profile_wait:
                        data["profile_wait"] = args.profile_wait
                    if args.home_wait:
                        data["home_wait"] = args.home_wait
                    netflix.save(tv.s.host, data)
                out = netflix.watch(tv, args.profile, args.show, args.season, args.episode, args.play,
                                    from_start=args.from_start)
            case "netflix-search":
                from . import netflix
                out = netflix.search(tv, args.show)
            case "netflix-find":
                from .netflix_search import search as find
                found = find(args.query)
                out = "\n".join(f"{r['title']} ({r['kind']}, {r['year']})  {r['poster']}" for r in found) or "Nothing found on Netflix."
            case "netflix-episode":
                from . import netflix
                out = netflix.open_episode(tv, args.season, args.episode)
            case "episodes":
                from .episodes import seasons
                data = seasons(args.show)
                out = "\n".join(f"Season {s['number']}: {len(s['episodes'])} episodes" for s in data["seasons"])
            case "netflix-close":
                from . import netflix
                out = netflix.close(tv)
            case "netflix-profiles":
                from . import netflix
                out = "Profiles, top to bottom: " + ", ".join(netflix.set_profiles(tv.s.host, args.names))
            case "gtv":
                out = _gtv(args)
            case "install-claude":
                from .install import install
                out = install(tv.s.host, args.config)
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
                out = "Pressed " + ", ".join(tv.press(args.keys))
            case "app":
                out = tv.open_app(args.name, args.params)
            case "app-info":
                out = "\n".join(tv.dial.raw(args.name))
            case "youtube":
                out = tv.play_youtube(args.video)
            case "youtube-link":
                out = tv.link_youtube(" ".join(args.code))
    except (TVError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
