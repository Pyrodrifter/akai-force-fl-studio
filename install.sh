#!/bin/sh
# Installs (or removes) the Akai Force Live Control script for FL Studio on macOS.
#
#   ./install.sh               install from this folder (or download if the files aren't here)
#   ./install.sh --uninstall   remove it
#   curl -fsSL https://raw.githubusercontent.com/Pyrodrifter/akai-force-fl-studio/main/install.sh | sh
#
# Note: Akai's Network MIDI driver only exists for Intel Macs, and the macOS
# path has not been tested on hardware yet.
set -e

REPO="Pyrodrifter/akai-force-fl-studio"
FILES="device_AkaiForce.py force_protocol.py"
HW="${FL_HARDWARE_DIR:-$HOME/Documents/Image-Line/FL Studio/Settings/Hardware}"
DEST="$HW/Akai Force Live"

if [ "$1" = "--uninstall" ]; then
    rm -rf "$DEST" && echo "Removed $DEST"
    exit 0
fi

HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo "")"
mkdir -p "$DEST"
for f in $FILES; do
    if [ -n "$HERE" ] && [ -f "$HERE/$f" ]; then
        cp "$HERE/$f" "$DEST/"
    else
        curl -fsSL "https://raw.githubusercontent.com/$REPO/main/$f" -o "$DEST/$f"
    fi
done
# your own plugin knob pages: installed once, never overwritten
f=force_plugin_maps.py
if [ -f "$DEST/$f" ]; then
    echo "Kept your $f"
elif [ -n "$HERE" ] && [ -f "$HERE/$f" ]; then
    cp "$HERE/$f" "$DEST/"
else
    curl -fsSL "https://raw.githubusercontent.com/$REPO/main/$f" -o "$DEST/$f" || true
fi
echo "Installed to: $DEST"

if [ "$(uname -m)" = "arm64" ]; then
    echo "Warning: this Mac has Apple Silicon. Akai's Network MIDI driver is Intel-only, so the Force can't connect."
fi
cat <<'EOF'

Next steps
  1. Install "Akai Network Driver" (inMusic Software Center or akaipro.com) and pair the Force.
  2. FL Studio > Options > MIDI Settings:
       Input  "Akai Network - DAW Control": enable, Controller type = "Akai Force (Live Control)", Port = 1
       Output "Akai Network - DAW Control": Port = 1 (the same number)
  3. On the Force: press MENU, tap LIVE CONTROL.
EOF
