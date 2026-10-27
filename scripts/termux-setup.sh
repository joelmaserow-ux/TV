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
pkg install -y python git python-cryptography

echo "==> Installing the remote"
# There are no prebuilt wheels for Android, so use the pure-Python versions of the
# async libraries rather than compiling them. Claude's MCP server isn't installed here:
# it needs packages that don't build on a phone, and the remote doesn't use it.
export AIOHTTP_NO_EXTENSIONS=1 YARL_NO_EXTENSIONS=1 MULTIDICT_NO_EXTENSIONS=1 \
       FROZENLIST_NO_EXTENSIONS=1 PROPCACHE_NO_EXTENSIONS=1 BUILD_EXTENSION=no \
       PIP_BREAK_SYSTEM_PACKAGES=1
pip install "samsungtvws[async,encrypted]>=3,<4" "pyytlounge>=3,<4" "yt-dlp>=2025.1.1"
pip install --no-deps --force-reinstall "$REPO"

echo "==> Adding the tv-remote command"
cat > "$PREFIX/bin/tv-remote" <<'SH'
#!/data/data/com.termux/files/usr/bin/sh
# Keep the phone from sleeping the remote while it runs.
termux-wake-lock
exec samsung-tv remote "$@"
SH
chmod +x "$PREFIX/bin/tv-remote"

echo "==> Setting up auto-start (needs the Termux:Boot app)"
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/tv-remote" <<'SH'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
exec samsung-tv remote >> "$HOME/tv-remote.log" 2>&1
SH
chmod +x "$HOME/.termux/boot/tv-remote"

cat <<'MSG'

Done. Next:
  1. Pair with the TV (TV on, a PIN appears on screen):   samsung-tv pair
  2. Link YouTube (code from YouTube > Settings > Link with TV code on the TV):
                                                          samsung-tv youtube-link 123 456 789 012
  3. Start the remote:                                    tv-remote
     It prints the address and PIN for the other phones.

To update later, run this script again.
MSG
