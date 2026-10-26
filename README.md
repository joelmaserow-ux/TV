# Samsung TV MCP server

An [MCP](https://modelcontextprotocol.io) server that lets Claude control a **Samsung UA55H6300**
(2014 H-series, Orsay OS) Smart TV at `192.168.1.106` over your home network.

| You ask Claude to… | Tool | How it works | Works on the UA55H6300? |
|---|---|---|---|
| Turn the TV **off** | `power_off` | Remote key over TCP port 55 | Yes |
| Turn the TV **on** | `power_on` | HDMI-CEC or Wake-on-LAN | Only with extra hardware (see below) |
| Set / nudge / mute **volume** | `set_volume`, `change_volume`, `mute`, `get_volume` | UPnP RenderingControl, falls back to remote keys | Yes |
| **Open an app** (YouTube, Netflix, Smart Hub, Source…) | `open_app`, `app_status`, `close_app` | DIAL (the protocol phones use to cast) | YouTube yes; others only if the app supports DIAL, otherwise it opens Smart Hub for you |
| **Play a YouTube video** | `play_youtube` | DIAL launch of YouTube with the video id | Yes, if the YouTube app on the TV still works |
| **Play a specific show** in another app | `open_app` + `send_keys` | Opens the app, then navigates/searches with remote keys | Best-effort; 2014 apps don't accept deep links |
| Press any **remote button** | `send_keys`, `list_keys` | Remote keys over port 55 | Yes |
| Figure out **what's wrong** | `diagnose` | Probes ports and discovery, tests pairing | Yes |

**Two honest limitations of this TV model**

1. **Power on.** In standby, 2014 H-series TVs switch their network chip off, so nothing on the
   network can wake them. `power_on` works only if you plug a small HDMI-CEC device (e.g. a
   Raspberry Pi) into the TV, or use an IR blaster. Turning **off** works fine.
2. **Bloatware/spyware.** Samsung's built-in apps on this firmware cannot be uninstalled, and no
   network protocol can remove them. What you *can* do is switch the tracking off and block it at
   your router. That is covered step by step in **[PRIVACY.md](PRIVACY.md)**.

---

## Step-by-step installation

You need a computer that **stays on the same home network as the TV**: a Mac, a Windows PC, or a
Raspberry Pi. Claude Desktop or Claude Code runs on that computer and starts this server.

### Step 1: Prepare the TV

1. Turn the TV on with its remote.
2. Give the TV a fixed address so `192.168.1.106` keeps working. In your router's admin page, find
   "DHCP reservation" (or "static lease") and reserve `192.168.1.106` for the TV.
   You can see the TV's current address under **Menu → Network → Network Status**.
3. Allow phones/computers to control it: **Menu → Network → AllShare Settings** (on some
   firmwares **Multimedia Device Settings**). Make sure it is **On** and nothing is set to "Deny".
4. Leave the TV on for the next steps.

### Step 2: Install Python 3.10 or newer

- **Mac:** install from <https://www.python.org/downloads/> (or `brew install python`).
- **Windows:** install from <https://www.python.org/downloads/>, and tick **"Add python.exe to PATH"**.
- **Raspberry Pi / Linux:** `sudo apt install python3 python3-venv git`.

Check it in a terminal (Mac: *Terminal*, Windows: *PowerShell*):

```bash
python3 --version     # Windows: python --version
```

### Step 3: Download this project

```bash
git clone https://github.com/joelmaserow-ux/TV.git samsung-tv-mcp
cd samsung-tv-mcp
```

(No git? Download the ZIP from the GitHub page, unzip it, and `cd` into the folder.)

### Step 4: Install it in a virtual environment

**Mac / Linux / Raspberry Pi**

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\pip install -e .
```

### Step 5: Pair with the TV and test it

With the TV on, run:

```bash
.venv/bin/samsung-tv diagnose        # Windows: .venv\Scripts\samsung-tv diagnose
```

How you pair depends on the TV's firmware, and `diagnose` tells you which one you have:

- **Port 55 open (older firmware):** the TV shows a prompt asking whether to allow
  "Claude TV Remote". Choose **Allow** with the TV remote within 30 seconds.
- **Port 55 closed, 8000/8080 open (newer firmware, encrypted pairing):** run

  ```bash
  .venv/bin/samsung-tv pair
  ```

  A 4-digit PIN appears on the TV. Type it into the terminal and press Enter. The credentials are
  saved in a `.samsung-tv-mcp` folder in your home folder.

Either way you only pair once.

A good result looks like this:

```
TV host: 192.168.1.106
  port 55    open    legacy remote (needed for keys/power off)
  port 7676  open    UPnP / AllShare
  ...
  UPnP volume control: found at http://192.168.1.106:7676/...
  DIAL app launching: found at http://192.168.1.106:7676/...
  remote (...): OK, sent KEY_INFO; you should see the info banner on the TV
```

Now try a few commands:

```bash
.venv/bin/samsung-tv volume            # show the volume
.venv/bin/samsung-tv volume 15         # set it to 15
.venv/bin/samsung-tv louder 3
.venv/bin/samsung-tv app YouTube
.venv/bin/samsung-tv youtube "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
.venv/bin/samsung-tv key KEY_MENU KEY_RETURN
.venv/bin/samsung-tv off
```

If any of these fail, see [Troubleshooting](#troubleshooting) before going on.

### Step 6: Find the full path to the server

You need the full path in the next step. From inside the project folder:

```bash
echo "$PWD/.venv/bin/samsung-tv-mcp"                     # Mac / Linux
```
```powershell
"$PWD\.venv\Scripts\samsung-tv-mcp.exe"                   # Windows
```

### Step 7a: Add it to Claude Desktop

Open Claude Desktop → **Settings → Developer → Edit Config**. That opens
`claude_desktop_config.json`. Add this (merge it with anything already there), using your path
from Step 6:

```json
{
  "mcpServers": {
    "samsung-tv": {
      "command": "/Users/you/samsung-tv-mcp/.venv/bin/samsung-tv-mcp",
      "env": {
        "SAMSUNG_TV_HOST": "192.168.1.106"
      }
    }
  }
}
```

On Windows the command looks like
`"C:\\Users\\you\\samsung-tv-mcp\\.venv\\Scripts\\samsung-tv-mcp.exe"` (note the double backslashes).

Quit Claude Desktop completely and reopen it. The tools appear under the tools (slider) icon in
the chat box.

### Step 7b: …or add it to Claude Code

```bash
claude mcp add samsung-tv -e SAMSUNG_TV_HOST=192.168.1.106 -- /full/path/to/.venv/bin/samsung-tv-mcp
```

Then run `/mcp` inside Claude Code to check that `samsung-tv` is connected.

### Step 8: Use it

Try asking Claude:

- "Turn the TV volume down to 12."
- "Mute the TV."
- "Open YouTube on the TV."
- "Play this on the TV: https://youtu.be/dQw4w9WgXcQ"
- "Find the official trailer for *Dune: Part Two* on YouTube and play it on the TV." (Claude needs
  web search to find the link.)
- "Open Smart Hub and go to the Netflix tile." (Claude will press arrow keys and Enter.)
- "Turn the TV off."

---

## Settings

Set these in the `env` block of the MCP config (or export them before running `samsung-tv`).

| Variable | Default | Meaning |
|---|---|---|
| `SAMSUNG_TV_HOST` | `192.168.1.106` | TV IP address |
| `SAMSUNG_TV_PORT` | `55` | Remote-control port (older firmware) |
| `SAMSUNG_TV_METHOD` | `auto` | `legacy` (port 55), `encrypted` (PIN pairing) or `auto` |
| `SAMSUNG_TV_CONFIG_DIR` | `~/.samsung-tv-mcp` | Where PIN-pairing credentials are saved |
| `SAMSUNG_TV_CLIENT_NAME` | `Claude TV Remote` | Name shown in the TV's Allow/Deny prompt |
| `SAMSUNG_TV_CLIENT_ID` | derived from this computer's MAC | Identity the TV remembers after "Allow" |
| `SAMSUNG_TV_USE_CEC` | `0` | `1` lets `power_on` use `cec-client` (HDMI-CEC) |
| `SAMSUNG_TV_MAC` | unset | TV's MAC address; lets `power_on` try Wake-on-LAN |
| `SAMSUNG_TV_RENDERING_CONTROL_URL` | auto-discovered | Override the UPnP volume URL |
| `SAMSUNG_TV_DIAL_URL` | auto-discovered | Override the DIAL apps URL |
| `SAMSUNG_TV_TIMEOUT` | `5` | Network timeout in seconds |

## Optional: turning the TV on with a Raspberry Pi (HDMI-CEC)

1. Turn on CEC on the TV: **Menu → System → Anynet+ (HDMI-CEC) → On**.
2. Plug a Raspberry Pi into any HDMI port on the TV and run this server on the Pi (Steps 2–7).
3. On the Pi: `sudo apt install cec-utils`, then test with `echo 'on 0' | cec-client -s -d 1`.
4. Add `"SAMSUNG_TV_USE_CEC": "1"` to the server's `env`.

## Troubleshooting

- **"Cannot reach the TV"**: the TV is off/in standby, the IP is wrong, or the computer is on a
  different network (e.g. a guest Wi-Fi). Check **Menu → Network → Network Status** on the TV.
- **No Allow prompt / "denied"**: go to **Menu → Network → AllShare Settings** (or
  *Multimedia Device Settings*), find "Claude TV Remote", and set it to **Allow**.
- **`diagnose` says port 55 is closed but 8000/8080 are open**: your firmware uses encrypted PIN
  pairing. Run `samsung-tv pair` (Step 5). If the PIN is rejected or it times out, run it again
  for a fresh PIN. To re-pair from scratch, delete the `.samsung-tv-mcp` folder in your home folder.
- **Volume control not found**: AllShare/DLNA is off. Turn it on (Step 1.3). `change_volume` and
  `mute` still work through remote keys.
- **YouTube opens but the video doesn't play / YouTube won't open**: YouTube has been dropping old
  Smart TV models. If the YouTube app doesn't work with the TV's own remote, it won't work here
  either. A Chromecast or Fire TV stick is the reliable fix.
- **An app isn't found**: only apps that register with DIAL can be opened by name. For anything
  else Claude opens Smart Hub and navigates with arrow keys.

## Development

```bash
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest
```

The tests run against fake TV endpoints (no real TV needed). The protocols are in
`src/samsung_tv_mcp/`: `legacy.py` (port-55 remote), `encrypted.py` (PIN pairing, via the
`samsungtvws` library), `upnp.py` (SSDP, UPnP volume, DIAL),
`power.py` (WoL/CEC), `tv.py` (the operations), `server.py` (MCP tools), `cli.py` (`samsung-tv`).
