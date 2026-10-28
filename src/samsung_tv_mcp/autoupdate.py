"""Keep a remote started by `samsung-tv autostart` on the newest version, with no typing.

Every 30 minutes it asks GitHub for the newest commit on the branch it was installed from.
When there's a newer one and nothing long is running, it exits; the autostart loop then
starts the remote again with `uvx --refresh`, which installs the new version.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

CHECK_EVERY = 30 * 60


def installed() -> tuple[str, str, str] | None:
    """(owner/repo, branch, commit) this copy was installed from by uv, or None."""
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        data = json.loads(distribution("samsung-tv-mcp").read_text("direct_url.json") or "{}")
    except (PackageNotFoundError, ValueError, FileNotFoundError):
        return None
    vcs = data.get("vcs_info") or {}
    url = data.get("url", "")
    if "github.com/" not in url or not vcs.get("commit_id") or not vcs.get("requested_revision"):
        return None
    repo = url.split("github.com/", 1)[1].removesuffix(".git").strip("/")
    return repo, vcs["requested_revision"], vcs["commit_id"]


def newest(repo: str, branch: str) -> str | None:
    """The newest commit on the branch. Asks git first: it's signed in to GitHub on this
    computer (that's how uv installed the remote), which a private repository needs."""
    import subprocess

    try:
        out = subprocess.run(["git", "ls-remote", f"https://github.com/{repo}", f"refs/heads/{branch}"],
                             capture_output=True, text=True, timeout=60,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.split()
        if out:
            return out[0]
    except (OSError, subprocess.SubprocessError):
        pass
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/commits/{branch}",
                                 headers={"Accept": "application/vnd.github.sha", "User-Agent": "samsung-tv-mcp"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode().strip() or None
    except OSError:
        return None


def start(is_busy) -> bool:
    """Watch for updates in the background (only under autostart). Returns whether it's on."""
    if os.environ.get("SAMSUNG_TV_AUTOUPDATE", "").strip() != "1":
        return False
    source = installed()
    if source is None:
        return False
    repo, branch, current = source

    def watch():
        while True:
            time.sleep(CHECK_EVERY)
            latest = newest(repo, branch)
            if latest and latest != current:
                while is_busy():
                    time.sleep(30)
                print(f"{time.strftime('%H:%M:%S')}  A new version is out; restarting to install it.", flush=True)
                os._exit(0)

    threading.Thread(target=watch, daemon=True, name="autoupdate").start()
    return True
