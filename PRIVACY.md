# Cleaning up the junk, bloatware and tracking on a Samsung UA55H6300

**What's possible on this model:** the 2014 H-series runs Samsung's locked Orsay OS. Apps that
came with the TV are part of the firmware and **cannot be uninstalled**, by this MCP server or by
anything else short of rooting the TV. What you can do is:

1. Switch off the data collection (viewing history, ad targeting, voice data) in the TV's menus.
2. Delete apps that were downloaded later, and stop Smart Hub popping up.
3. Block Samsung's tracking and ad servers at the network level.
4. If you don't use the built-in apps at all, keep the TV off the internet entirely.

Menu names vary a little between firmware versions. If an item isn't where it says below, look
in the neighbouring menus (**Smart Features**, **Support**, **System**).

The MCP server deliberately does **not** click through these menus for you. They differ between
firmwares, so pressing keys without seeing the screen could change the wrong setting. It's a
one-time job that takes about 10 minutes with the remote.

---

## 1. Turn off data collection (most important)

Go to **Menu → Smart Features → Terms & Policy** (some firmwares: **Menu → Support → Terms &
Policy**, or from inside **Smart Hub → Settings → Terms & Policy**). Open each item and
**disagree / turn off**:

| Setting | What it does | Turn off? |
|---|---|---|
| **SyncPlus and Marketing** / **Viewing Information Services** | Identifies what's on screen ("ACR"), including from HDMI inputs, and reports it to Samsung | **Yes**: this is the main tracker |
| **Interest-Based Advertisement** | Uses that viewing data to target ads | **Yes** |
| **Voice Recognition Services** / **Nuance Voice Recognition** | Sends voice commands from the Smart Touch remote to a cloud service | **Yes**, unless you use voice control |
| **Privacy Notice** / **Smart Hub Terms & Conditions** | Required for Smart Hub apps (YouTube, Netflix…) | Leave on if you use any built-in apps |

Then:

- **Menu → Smart Features → Auto Run Smart Hub → Off** (stops Smart Hub launching at power-on).
- **Menu → Smart Features → Auto Run Last App → Off**.
- **Menu → System → Voice Control → Off** and **Motion Control → Off**, if present.
- **Menu → Smart Features → Samsung Account → Sign out / remove account**, if you never use it.

Keep **Menu → Network → AllShare Settings** on: this MCP server needs it.

## 2. Remove downloaded apps and declutter Smart Hub

1. Press the **Smart Hub** button.
2. Go to the apps panel (**Apps → My Apps**).
3. Highlight an app you didn't install on purpose, press and hold **Enter** (or press **Tools**),
   then choose **Delete**. Built-in apps show **Move**/**Lock** but no **Delete**.
4. For built-in apps you can't delete, use **Lock** (PIN-protects them) or move them to the end.

**Start fresh:** **Menu → Smart Features → Reset Smart Hub** removes every downloaded app, signed-in
account and saved app data. The default PIN is `0000`. Afterwards, decline the optional
agreements from section 1 when Smart Hub asks again.

## 3. Block tracking at the network level

This stops the TV contacting tracking/ad servers even if a setting turns itself back on. Use your
router's domain blocking if it has it, or a DNS filter such as **Pi-hole** or **AdGuard Home**.

**Safe to block (ads, ACR and telemetry):**

```
samsungads.com
samsungacr.com
samsungcloudsolution.com
samsungcloudsolution.net
samsungqbe.com
```

**Blocking these breaks things. Only block them if you never use the built-in apps:**

```
internetat.tv            # Smart Hub app store and app servers
samsungotn.net           # firmware updates (this model no longer gets new firmware anyway)
```

**Best practice:** before blocking, let the TV run for a day with Pi-hole/AdGuard watching it.
Then filter the query log by the TV's IP (`192.168.1.106`) to see exactly which domains *your*
firmware contacts. Block the advertising/analytics ones, check YouTube still works, and repeat.

## 4. Take the TV offline (maximum privacy)

If you watch through a streaming stick, game console or set-top box anyway, the TV's own apps
are pure liability. In your router, block **internet** access for `192.168.1.106` (many routers call
this "Parental controls", "Access control" or "Block device", and some let you block internet
while keeping the local network).

What still works with the TV offline:

- ✅ this MCP server's power off, volume, mute and remote keys (they stay on your home network)
- ❌ YouTube and other built-in apps (they need the internet)

## About rooting (SamyGO)

The SamyGO community has root tools for some Orsay TVs, and they can genuinely remove things.
They are **not recommended** here. They depend on exact firmware versions, a mistake can
permanently brick the TV, and you get little extra privacy beyond sections 1–4.
