"""Add this server to Claude Desktop's config without disturbing anything else in it."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

PACKAGE_SPEC = "git+https://github.com/joelmaserow-ux/TV@ccr-5fac4f84-5wt34a"


def config_candidates() -> list[Path]:
    home = Path.home()
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        paths = [Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "Claude", local / "Claude"]
        # Older Microsoft Store installs keep it in a per-package folder.
        packages = local / "Packages"
        paths += sorted(packages.glob("Claude_*/LocalCache/Roaming/Claude")) if packages.exists() else []
    elif sys.platform == "darwin":
        paths = [home / "Library/Application Support/Claude"]
    else:
        paths = [home / ".config/Claude"]
    return [p / "claude_desktop_config.json" for p in paths]


def find_config() -> Path:
    candidates = config_candidates()
    # The folder Claude Desktop actually runs from has its logs in it. Store installs can
    # leave a stale package folder behind (marked ".user-data-left..."), so check this first.
    for path in candidates:
        if (path.parent / "logs").is_dir():
            return path
    for path in candidates:
        if path.exists():
            return path
    for path in candidates:
        if path.parent.exists():
            return path
    return candidates[0]


def install(host: str) -> str:
    path = find_config()
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    try:
        config = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} isn't valid JSON right now ({exc}), so I won't touch it. "
            "Fix or empty the file, then run this again."
        ) from exc
    if not isinstance(config, dict):
        raise ValueError(f"{path} doesn't contain a JSON object; not changing it.")

    backup = None
    if path.exists():
        backup = path.with_name(path.name + ".backup")
        shutil.copy2(path, backup)

    servers = config.setdefault("mcpServers", {})
    servers["samsung-tv"] = {
        "command": shutil.which("uvx") or "uvx",
        "args": ["--from", PACKAGE_SPEC, "samsung-tv-mcp"],
        "env": {"SAMSUNG_TV_HOST": host},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    lines = [f"Added 'samsung-tv' to {path}"]
    if backup:
        lines.append(f"Your previous config is saved as {backup}")
    lines.append("Now quit Claude Desktop completely and reopen it.")
    return "\n".join(lines)
