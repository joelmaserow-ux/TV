"""Start the family remote by itself whenever you sign in to the Windows laptop.

`samsung-tv autostart` puts a small script in your Startup folder that runs
`samsung-tv remote` hidden in the background (its output goes to remote.log), and starts
it straight away. `samsung-tv autostart --off` removes it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .encrypted import credentials_path

SOURCE = "git+https://github.com/joelmaserow-ux/TV@ccr-5fac4f84-5wt34a"
SCRIPT = "samsung-tv-remote.vbs"


def startup_folder() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise ValueError("Starting with the laptop is set up for Windows only.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _vbs(command: str) -> str:
    # VBScript doubles quotes inside strings; window style 0 = hidden, False = don't wait.
    return (
        'Set shell = CreateObject("WScript.Shell")\r\n'
        f'shell.Run "cmd /c {command.replace(chr(34), chr(34) * 2)}", 0, False\r\n'
    )


def install(source: str = SOURCE, port: int = 8765, start_now: bool = True) -> Path:
    uvx = shutil.which("uvx") or "uvx"
    log = credentials_path("remote").with_name("remote.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    command = f'"{uvx}" --from {source} samsung-tv remote --port {port} > "{log}" 2>&1'
    path = startup_folder() / SCRIPT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_vbs(command), encoding="utf-8")
    if start_now and sys.platform == "win32":
        subprocess.Popen(["wscript", str(path)], close_fds=True)
    return path


def uninstall() -> bool:
    path = startup_folder() / SCRIPT
    if path.exists():
        path.unlink()
        return True
    return False
