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
    fonts-dejavu-core alsa-utils x11-xkb-utils
# Reads the keyboard's special keys (camera, on-screen keyboard …) that X cannot pass on.
sudo apt-get install -y --no-install-recommends python3-evdev \
    || echo "python3-evdev is not available: a few special keys (such as the keyboard key) will not work." >&2
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

echo "== Allowing access to the GPIO pins (distance sensor), the keyboard's special keys and the backlight"
sudo usermod -aG gpio,video,audio,input "$USER" || true
# Screens with a backlight Quill can dim (such as the official Raspberry Pi touchscreen): let the
# video group change it. HDMI screens have none; Quill then dims the picture instead.
sudo tee /etc/udev/rules.d/90-quill-backlight.rules >/dev/null <<'RULES'
SUBSYSTEM=="backlight", RUN+="/bin/chgrp video /sys/class/backlight/%k/brightness", RUN+="/bin/chmod g+w /sys/class/backlight/%k/brightness"
RULES

echo "== The power button (a push button between GPIO 3 and GND, see SETUP.md)"
# When the Pi is off, connecting GPIO 3 to GND turns it on: the Pi does that by itself. While it is on,
# this overlay makes the same button a key (KEY_POWER) that Quill reads: a short press locks the screen,
# holding it shuts down.
BOOT_CONFIG=/boot/firmware/config.txt
[ -f "$BOOT_CONFIG" ] || BOOT_CONFIG=/boot/config.txt
if [ -f "$BOOT_CONFIG" ]; then
    grep -q '^dtoverlay=gpio-shutdown' "$BOOT_CONFIG" || echo 'dtoverlay=gpio-shutdown' | sudo tee -a "$BOOT_CONFIG" >/dev/null
else
    echo "No config.txt found: add the line dtoverlay=gpio-shutdown to it yourself." >&2
fi
# The system itself must not turn off at a short press (Quill decides); if Quill is not running,
# holding the button for 5 seconds still turns the Pi off.
sudo mkdir -p /etc/systemd/logind.conf.d
sudo tee /etc/systemd/logind.conf.d/90-quill-power.conf >/dev/null <<'LOGIND'
[Login]
HandlePowerKey=ignore
HandlePowerKeyLongPress=poweroff
LOGIND

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
# Inkwell's keyboard is Portuguese (Loom → Keyboard can change this).
setxkbmap pt || true
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
