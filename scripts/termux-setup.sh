#!/data/data/com.termux/files/usr/bin/bash
# Install the family TV remote on an Android phone, in Termux.
#
#   curl -fsSL https://raw.githubusercontent.com/joelmaserow-ux/TV/ccr-5fac4f84-5wt34a/scripts/termux-setup.sh | bash
#
# The phone must stay at home on the TV's Wi-Fi: it's what sends the commands to the TV.
set -euo pipefail

REPO="git+https://github.com/joelmaserow-ux/TV@ccr-5fac4f84-5wt34a"

echo "==> Installing Python and tools (this takes a few minutes the first time)"
pkg update -y
# cryptography comes prebuilt from Termux; building it with pip would need Rust.
pkg install -y python git python-cryptography procps

echo "==> Installing the remote"
# There are no prebuilt wheels for Android, so use the pure-Python versions of the
# async libraries rather than compiling them. Claude's MCP server isn't installed here:
# it needs packages that don't build on a phone, and the remote doesn't use it.
export AIOHTTP_NO_EXTENSIONS=1 YARL_NO_EXTENSIONS=1 MULTIDICT_NO_EXTENSIONS=1 \
       FROZENLIST_NO_EXTENSIONS=1 PROPCACHE_NO_EXTENSIONS=1 BUILD_EXTENSION=no \
       PIP_BREAK_SYSTEM_PACKAGES=1
pip install "samsungtvws[async,encrypted]>=3,<4" "pyytlounge>=3,<4" "yt-dlp>=2025.1.1" "androidtvremote2>=0.3,<1"
pip install --no-deps --force-reinstall "$REPO"

echo "==> Adding the tv-remote command"
cat > "$PREFIX/bin/tv-remote" <<'SH'
#!/data/data/com.termux/files/usr/bin/sh
# Run the remote in the background (if it isn't already), so it keeps going after you
# leave Termux. Its messages go to ~/tv-remote.log.
if pgrep -f "samsung-tv remote" > /dev/null; then
  echo "The TV remote is already running: open http://localhost:8765"
  exit 0
fi
nohup samsung-tv remote "$@" > "$HOME/tv-remote.log" 2>&1 &
sleep 4
grep -E "PIN|Projector" "$HOME/tv-remote.log"
echo "The TV remote is running in the background: open http://localhost:8765"
SH
chmod +x "$PREFIX/bin/tv-remote"

echo "==> Starting the remote whenever Termux opens"
touch "$HOME/.bashrc"
if ! grep -q "tv-remote # autostart" "$HOME/.bashrc"; then
  echo 'tv-remote > /dev/null 2>&1 # autostart: start the TV remote if it is not running' >> "$HOME/.bashrc"
fi

echo "==> Setting up auto-start (needs the Termux:Boot app)"
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/tv-remote" <<'SH'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
exec samsung-tv remote >> "$HOME/tv-remote.log" 2>&1
SH
chmod +x "$HOME/.termux/boot/tv-remote"

cat <<'MSG'

Done. Next (only the parts for what you have):
  Projector (Google TV):
    1. Pair (projector on; a code appears on it):  samsung-tv gtv --ip 192.168.86.177 pair
    2. Link YouTube on it (YouTube > Settings > Link with TV code on the projector):
                                                   samsung-tv --gtv 192.168.86.177 youtube-link <the 12-digit code on screen>
    3. Start the remote with it (remembered):      pkill -f "samsung-tv remote"; tv-remote --projector 192.168.86.177
  Samsung TV:
    1. Pair (TV on, a PIN appears on screen):      samsung-tv pair
    2. Link YouTube:                               samsung-tv youtube-link <the 12-digit code on screen>
  Then open  http://localhost:8765  in Chrome on this phone (Add to Home screen).
  It keeps running in the background. After the phone restarts, just open Termux once.
  So Android doesn't stop it: Settings > Apps > Termux > Battery > Unrestricted.

To update later, run this script again.
MSG
