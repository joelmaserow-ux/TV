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

## Quick setup (Windows/Mac, using uv)

This is the fastest route and what was used on the UA55H6300. The longer manual route follows below.

1. **Install uv.** Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
   Mac: `curl -LsSf https://astral.sh/uv/install.sh | sh`. Then reopen the terminal.
2. **Check the TV's IP** under **Menu → Network → Network Status** (here: `192.168.1.106`), and
   ideally reserve it in your router.
3. **Pair the remote** (TV on). A PIN appears on the TV; type it in:
   ```powershell
   $tv = "git+https://github.com/joelmaserow-ux/TV@ccr-5fac4f84-5wt34a"
   uvx --from $tv samsung-tv --host 192.168.1.106 pair
   ```
4. **Set up YouTube** (once):
   - On the TV, open YouTube and **sign in** (code at youtube.com/activate). As a guest, the app
     stops on an account picker when opened and ignores casts.
   - In YouTube on the TV, open **Settings → Link with TV code** and run
     `uvx --from $tv samsung-tv youtube-link 123 456 789 012` with the code shown.
5. **Test:** `uvx --from $tv samsung-tv youtube "https://youtu.be/aqz-KE-bpKQ"`.
6. **Add to Claude Desktop:** run `uvx --from $tv samsung-tv install-claude` (it backs up and merges your config), then fully restart Claude Desktop. Or edit it by hand (**Settings → Developer → Edit Config**):
   ```json
   {
     "mcpServers": {
       "samsung-tv": {
         "command": "uvx",
         "args": ["--from", "git+https://github.com/joelmaserow-ux/TV@ccr-5fac4f84-5wt34a", "samsung-tv-mcp"],
         "env": { "SAMSUNG_TV_HOST": "192.168.1.106" }
       }
     }
   }
   ```
   If Claude can't find `uvx`, use its full path (`where.exe uvx` on Windows, `which uvx` on Mac).
   On Microsoft Store installs the real file is the one **Settings → Developer → Edit config** opens
   (e.g. `%LOCALAPPDATA%\Claude-Data\claude_<id>\claude_desktop_config.json`). If the server
   doesn't show up, quit Claude Desktop and pass that path: `samsung-tv install-claude --config "<path>"`.

After an update to this repo, run any command once with `uvx --refresh --from $tv ...` to pick it up.

---

## Family remote (phones and laptops)

A web remote anyone on your home Wi-Fi can use: power off, volume, arrows/OK, playback, apps,
"paste a YouTube link", and typing into the TV's keyboard.

```powershell
uvx --from $tv samsung-tv remote
```

It prints an address like `http://192.168.1.50:8765` and a 4-digit PIN. Open the address on each
phone or laptop, enter the PIN once, and use **Add to Home Screen** (iPhone: Share menu; Android:
browser menu) so it opens like an app. Keep the window running; the computer must be on.

- The first time, Windows asks whether to let Python on the network: allow **Private networks**.
- `--pin 1234` sets your own PIN (it's remembered); `--port` changes the port.
- **Run `samsung-tv button-test` once.** It presses every remote button on the TV, asks whether
  it worked, tries alternative codes, and hides buttons the TV can't do. Retest single buttons
  with e.g. `samsung-tv button-test Off Pause`.
- **Search YouTube** on the remote searches from the computer and shows results on your phone;
  tap one to play it on the TV. No typing on the TV needed. (Claude can do the same with
  `search_youtube`.)
- **Apps:** at startup the remote checks which apps the TV can open directly and shows a button
  for each (see them with `samsung-tv apps`). **All apps** opens Smart Hub for the rest.
- Typing into the TV's own keyboard isn't supported by the UA55H6300, so the remote doesn't offer it.
- For a remote that's always available, run it on an always-on machine such as a Raspberry Pi.

---

## Start the remote with the laptop

So the family remote is always there while the laptop is on, run this once:

```powershell
uvx --from $tv samsung-tv autostart
```

It starts the remote now and every time you sign in, hidden in the background (output in
`~/.samsung-tv-mcp/remote.log`), fetches the newest version each start, restarts it if it ever
stops, and prints the address and PIN for phones. Nothing to paste again after this. Keep the laptop
awake while you want to use it. `samsung-tv autostart --off` undoes it.

## Google TV / Android TV devices (e.g. the TOPTRO TP3 projector)

Pair once (a code appears on the screen), then control it from the command line:

```powershell
uvx --from $tv samsung-tv gtv --ip 192.168.1.50 pair
uvx --from $tv samsung-tv gtv --ip 192.168.1.50 status
uvx --from $tv samsung-tv gtv --ip 192.168.1.50 key up up ok
uvx --from $tv samsung-tv gtv --ip 192.168.1.50 volume 20
uvx --from $tv samsung-tv gtv --ip 192.168.1.50 app Disney+
uvx --from $tv samsung-tv gtv --ip 192.168.1.50 link https://www.youtube.com/watch?v=aqz-KE-bpKQ
uvx --from $tv samsung-tv gtv --ip 192.168.1.50 type rick and morty
uvx --from $tv samsung-tv gtv --ip 192.168.1.50 power off
```

To add it to the family remote (a TV / Projector switch appears at the top), start the remote
with `samsung-tv remote --projector 192.168.0.71` once; it's remembered. Netflix and YouTube on it
use the same routines as the TV (`samsung-tv --gtv <ip> netflix Ben --show "..."`); Netflix is
force-stopped from Settings first so it reopens on the profile screen.

Typing from the remote's Remote tab goes live onto the projector's open search box. Apps
differ in how they take typed text, so if typing goes wrong in one (say the home screen's
search), open that search box and run the yes/no test with the remote closed. It checks
typing, deleting, Clear and a quicker burst mode, and saves what works for that app:

```powershell
uvx --from $tv samsung-tv gtv --ip 192.168.86.177 typetest
```

(`typetest letters`, `typetest delete` and `typetest fast` run just one part.)

Set `GOOGLE_TV_HOST` to skip `--ip`. It uses the same protocol as the Google TV phone app
(`androidtvremote2`); no developer mode needed.

## Run the remote on an Android phone (no laptop)

Any Android phone that **stays at home on the TV's Wi-Fi** can run the family remote instead of a
computer. (iPhones can't.) If it's a phone you carry around, the remote only works while it's home.

1. Install **Termux** from F-Droid (https://f-droid.org/packages/com.termux/) — the Play Store
   build is older. Optionally also install **Termux:Boot** from F-Droid and open it once, so the
   remote starts by itself when the phone restarts.
2. Open Termux and run:
   ```sh
   curl -fsSL https://raw.githubusercontent.com/joelmaserow-ux/TV/ccr-5fac4f84-5wt34a/scripts/termux-setup.sh | bash
   ```
3. Pair with the TV and link YouTube again from the phone (`samsung-tv pair`, then
   `samsung-tv youtube-link <code>`), then start it with `tv-remote`.
4. In Android settings, set Termux's battery use to **Unrestricted** (Apps → Termux → Battery)
   and keep the phone on its charger, so Android doesn't stop the remote in the background.

Other phones open the address `tv-remote` prints; on the host phone itself use
`http://localhost:8765`. Claude's MCP server isn't installed on the phone; keep using the PC for Claude.

---

## Step-by-step installation (manual)

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
| `SAMSUNG_TV_YOUTUBE_STARTUP` | `15` | Seconds to let a freshly opened YouTube app load before casting |

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
- **YouTube opens but says "This video is unavailable"**: the TV's YouTube app can't take a video
  passed at launch. Link it once: on the TV open **YouTube → Settings → Link with TV code** (older
  apps: **Pair device**), then run `samsung-tv youtube-link 123 456 789 012` with the code shown, or
  ask Claude to link it. Afterwards `play_youtube` casts the way the phone app does.
- **YouTube goes back to "choose an account" / sign-in**: sign in to YouTube on the TV. In guest
  mode the app sits on the account picker when opened and drops casts.
- **YouTube won't open at all**: YouTube has been dropping old
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
