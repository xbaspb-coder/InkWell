#!/bin/sh
# Sets up a Raspberry Pi (Raspberry Pi OS Lite) as Inkwell: on power-up it logs in by itself
# and starts Quill.OS full screen. Run it once, as your normal user (not root), while the Pi
# is connected to your home Wi-Fi:
#
#     sh pi/install.sh
#
# Running it again is safe: it only rewrites the files it owns.
set -eu

if [ "$(id -u)" -eq 0 ]; then
    echo "Please run this as your normal user, not with sudo. It asks for sudo itself when needed." >&2
    exit 1
fi

QUILL_DIR=$(cd "$(dirname "$0")/.." && pwd)
if [ ! -f "$QUILL_DIR/quill.py" ]; then
    echo "Could not find quill.py next to the pi folder ($QUILL_DIR)." >&2
    exit 1
fi
echo "Quill.OS folder: $QUILL_DIR"

echo "== Installing packages (this can take 10-20 minutes on a Raspberry Pi 3 A+)"
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    xserver-xorg xserver-xorg-input-libinput xinit x11-xserver-utils matchbox-window-manager \
    python3 python3-tk python3-pil python3-pil.imagetk python3-gpiozero \
    fonts-dejavu-core alsa-utils
# The GPIO library gpiozero uses on current Raspberry Pi OS (missing on very old releases).
sudo apt-get install -y python3-lgpio || echo "python3-lgpio is not available here; gpiozero will use another library."

echo "== Installing the web engine for OG Browser and XApps (WebKitGTK)"
sudo apt-get install -y --no-install-recommends python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
    || sudo apt-get install -y --no-install-recommends python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.0 \
    || echo "The web engine could not be installed: OG Browser and XApps will not open." >&2

echo "== Adding 1 GB of swap on the memory card (the Pi 3 A+ has only 512 MB of memory)"
if [ -f /etc/dphys-swapfile ]; then
    sudo sed -i -e 's/^#\?CONF_SWAPSIZE=.*/CONF_SWAPSIZE=1024/' -e 's/^#\?CONF_MAXSWAP=.*/CONF_MAXSWAP=2048/' /etc/dphys-swapfile
    grep -q '^CONF_SWAPSIZE=' /etc/dphys-swapfile || echo 'CONF_SWAPSIZE=1024' | sudo tee -a /etc/dphys-swapfile >/dev/null
    sudo dphys-swapfile setup && sudo dphys-swapfile swapon || echo "Swap could not be resized; it will be after a restart." >&2
else
    echo "This system does not use dphys-swapfile; leaving its swap settings as they are."
fi

echo "== Allowing access to the GPIO pins (for the distance sensor)"
sudo usermod -aG gpio,video,audio,input "$USER" || true

echo "== Starting Quill.OS automatically after power-up"
# Log in on the screen automatically (console autologin).
if command -v raspi-config >/dev/null 2>&1; then
    sudo raspi-config nonint do_boot_behaviour B2
else
    echo "raspi-config not found: turn on console autologin yourself." >&2
fi

# The graphical session: no screen blanking, a tiny window manager for keyboard focus, then Quill.
cat > "$HOME/.xinitrc" <<EOF
#!/bin/sh
# Written by Quill.OS pi/install.sh
xset s off
xset s noblank
xset -dpms
matchbox-window-manager -use_titlebar no &
cd "$QUILL_DIR"
exec python3 "$QUILL_DIR/quill.py" --fullscreen
EOF
chmod +x "$HOME/.xinitrc"

# Start the graphical session on the screen's own console (not over SSH).
MARK="# Quill.OS: start the desktop on the Pi's screen"
PROFILE="$HOME/.profile"
touch "$PROFILE"
if ! grep -qF "$MARK" "$PROFILE"; then
    cat >> "$PROFILE" <<'EOF'

# Quill.OS: start the desktop on the Pi's screen
if [ -z "${DISPLAY:-}" ] && [ "$(tty)" = /dev/tty1 ]; then
    exec startx 2>"$HOME/.quill-x.log"
fi
EOF
fi

echo
echo "Done. Next steps (see pi/SETUP.md):"
echo "  1. Pair the Bluetooth keyboard (bluetoothctl)."
echo "  2. Connect to the camera's Wi-Fi network: sudo nmcli dev wifi connect \"ELEGOO-...\""
echo "  3. Restart with: sudo reboot"
