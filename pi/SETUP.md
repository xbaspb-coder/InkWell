# Building Inkwell: setup and wiring

Inkwell is made of these parts:
- a Raspberry Pi 3 Model A+, which runs Quill.OS;
- a 7-inch HDMI touchscreen, a USB trackpad and a USB keyboard (Portuguese layout), joined through a small USB hub;
- an HC-SR04 distance sensor (the "eyes"), which warns when someone sits too close to the screen;
- the ELEGOO ESP32 camera module, used by the Iris camera app.

It runs Quill.OS, plus OG Browser (your original OG_Browser.html) and apps from XApps, the app store.

## 1. Parts list

| Part | Notes |
|---|---|
| Raspberry Pi 3 Model A+ | Runs Quill.OS |
| microSD card, 32 GB or more | Holds the operating system, plus 1 GB of "swap" (see below) |
| 7-inch HDMI touchscreen | Picture through HDMI, touch through USB |
| USB trackpad | Works together with the touchscreen |
| USB hub with 4 ports | The Pi 3 A+ has only one USB port; the hub gives room for the touchscreen's touch cable, the trackpad, the keyboard and a Wi-Fi adapter |
| USB Wi-Fi adapter (recommended, about 5–10 €) | Lets the Pi use the camera's Wi-Fi network and your home internet at the same time (see step 6) |
| USB keyboard (Portuguese layout) | Its special keys work in Quill.OS (see step 4) |
| HC-SR04 distance sensor | Wired to the Pi's GPIO pins |
| Resistors: one 1 kΩ, one 2 kΩ | Protect the Pi from the sensor's 5 V signal |
| ELEGOO ESP32 camera module | Powered through its USB-C socket |
| Battery pack and 5 V step-down converter (3 A or more) | Powers the Pi, the screen and the camera |
| Breadboard and jumper wires | For the sensor wiring |
| Push button (momentary, 2 legs or 4 legs) | The power button: turns the Pi on, locks the screen, and shuts down when held (see step 5) |

## 2. Install the operating system

1. On another computer, open **Raspberry Pi Imager** and choose:
   - **Device:** Raspberry Pi 3
   - **Operating system:** Raspberry Pi OS (other) → **Raspberry Pi OS Lite (32-bit)**. The Lite version leaves more of the Pi's 512 MB of memory for Quill.OS.
2. In the Imager's settings:
   - set a user name and password;
   - enter your **home Wi-Fi** name and password, which the Pi needs to download its software;
   - turn on **SSH**, so you can type commands from another computer before the keyboard is paired.
3. Write the card, put it in the Pi, connect the screen, and switch the Pi on.

## 3. Copy Quill.OS and run the setup script

Log in on the Pi, or connect from another computer with `ssh yourname@raspberrypi.local`, and type:

```sh
sudo apt-get install -y git
git clone -b claude/quill-os-discussion-36w1y3 https://github.com/xbaspb-coder/InkWell.git
cd InkWell
sh pi/install.sh
```

If the repository is private, Git asks you to sign in. You can also download the code as a ZIP from GitHub and copy it to the Pi on a USB stick.

The script does the following:
- installs the graphics system, Python, Tkinter, Pillow and gpiozero;
- installs the web engine (WebKitGTK) that runs OG Browser and XApps;
- installs the reader for the keyboard's special keys (python3-evdev) and sets the Portuguese keyboard layout;
- sets up the power button (step 5) and the safe shut-down;
- makes 1 GB of swap on the memory card;
- turns on automatic login;
- makes Quill.OS start full screen every time the Pi powers on.

## 4. The keyboard

Plug the keyboard into the USB hub. The setup script sets the Portuguese layout, so Ç, º, ª, « », € and the accents type as printed on the keys.

What the special keys do in Quill.OS:

| Key | Picture on it | What it does |
|---|---|---|
| F1 / F2 | Sun, small / big | Brightness down / up (in steps of 10 %, from 20 % to 100 %) |
| F3 | Magnifier | Opens or closes the Inkwell (search) |
| F4 | Camera | Opens Iris, the camera app |
| F5 | Keyboard | Shows or hides the on-screen keyboard |
| F6 | Stop | Stops the music in Lyre |
| F7 / F8 / F9 | Previous / play-pause / next | Controls the music in Lyre (opens Lyre's player if needed) |
| F10 / F11 / F12 | Mute / volume down / volume up | Volume, in steps of 10 % |
| Top left | Rectangle (windows) | Spread: shows all open windows |
| Top right | Padlock | A short press locks the screen. **Hold it for 2.5 seconds to shut the Raspberry Pi down** |
| CMD | ⌘ | On its own it opens the Inkwell; with another key it works like Ctrl (CMD+C copies, CMD+V pastes, CMD+S saves) |
| Fn | — | Handled inside the keyboard itself: it usually switches the top row between these actions and plain F1–F12 |

A box in the middle of the screen shows the new level when you change the volume or the brightness. On the lock screen only volume, brightness and the on-screen keyboard work.

**Loom → Keyboard** shows the name and number of the last key you pressed, lets you give every special key a different action, and lets you change the layout. If a key sends a plain F number (for example F4 instead of the camera code), press it there and choose **Give this key an action**.

The **on-screen keyboard** (F5, or Loom → Keyboard) is for typing with a finger. It types into the text box you touched last, moves to the top of the screen when that box would be hidden under it, and works on the lock screen and in dialogs. **⇧** gives one capital letter (twice for Caps Lock), **?123** gives symbols and accented letters (á à â ã é ê í ó ô õ ú ç €), **⇅** moves it to the other edge, and **⌄** hides it. Holding **⌫** or an arrow repeats it.

## 5. Wire the distance sensor (HC-SR04)

Switch the Pi off before wiring. The pin numbers below are the Pi's physical pin positions.

| HC-SR04 pin | Connects to |
|---|---|
| VCC | Pi **5 V** (pin 2) |
| GND | Pi **GND** (pin 6) |
| TRIG | Pi **GPIO 23** (pin 16) |
| ECHO | **1 kΩ resistor** → Pi **GPIO 24** (pin 18) |

Then add a **2 kΩ resistor** from GPIO 24 (the Pi side of the 1 kΩ resistor) to **GND**.

```
ECHO ──[ 1 kΩ ]──┬── GPIO 24 (pin 18)
                 │
              [ 2 kΩ ]
                 │
                GND
```

**Never connect ECHO straight to the Pi.** The sensor sends back 5 V, and the Pi's pins accept only 3.3 V. The two resistors reduce the signal to about 3.3 V.

Mount the sensor beside the screen, facing the person using the laptop. Its two "eyes" must point forward with nothing in front of them.

### The power button

The padlock key can shut the Pi down, but **no keyboard key can turn it on again**: a switched-off Raspberry Pi does not listen to USB. The only way to wake a Pi 3 A+ is to connect **GPIO 3** to **GND** for a moment, so add a small push button for that:

| Button leg | Connects to |
|---|---|
| One leg | Pi **GPIO 3** (pin 5) |
| The other leg | Pi **GND** (pin 9) |

(With a 4-leg button, use two legs on opposite corners.) No resistor is needed. GPIO 3 is not used by anything else in Inkwell.

What the button does:
- **When the Pi is off:** press it once and the Pi turns on (Quill.OS starts as usual).
- **When Quill.OS is running:** it works like the padlock key — a short press locks the screen, holding it for 2.5 seconds shuts down.
- If Quill.OS has stopped for some reason, holding the button for 5 seconds still shuts the Pi down safely.

Holding the padlock key or the button shows a box saying **Keep holding to shut down** with a bar that fills up; let go before it is full to cancel. Quill saves everything, closes the apps and turns the Pi off. Wait until the **green light on the Pi stops flashing** before unplugging the battery.

"Off" here means the Pi has stopped but is still connected to the battery, which still uses a little power (as does the screen if it has no switch). If you will not use Inkwell for a few days, disconnect the battery.

## 6. The camera

1. Power the ELEGOO camera through its **USB-C socket**, from the 5 V supply.
2. It creates its own Wi-Fi network, named **ELEGOO-** followed by letters and numbers. Connect the Pi to it:

   ```sh
   nmcli dev wifi list
   sudo nmcli dev wifi connect "ELEGOO-XXXXXXXXXXXX"
   ```

   To make the Pi choose the camera's network whenever the camera is on:

   ```sh
   sudo nmcli connection modify "ELEGOO-XXXXXXXXXXXX" connection.autoconnect-priority 10
   ```

3. The Pi's built-in Wi-Fi can join only one network at a time. While it is connected to the camera, it has **no internet**, so OG Browser and XApps cannot go online. There are two ways to deal with this:
   - **Recommended: a USB Wi-Fi adapter on the hub.** Keep the built-in Wi-Fi (`wlan0`) on your home network, and connect the adapter (`wlan1`) to the camera:

     ```sh
     sudo nmcli dev wifi connect "ELEGOO-XXXXXXXXXXXX" ifname wlan1
     ```

     The camera's network then carries only the camera, and the internet keeps working.
   - **Without an adapter:** switch networks when you need to. Install software (step 3) while the Pi is still on your home Wi-Fi.

Quill.OS looks for the camera at `http://192.168.4.1`, which is the ELEGOO camera's usual address. You can change it in **Loom → Eyes & camera**.

## 7. Power

| Part | Needs |
|---|---|
| Raspberry Pi 3 A+ | 5 V, up to 2.5 A, through its micro-USB power socket |
| 7-inch screen | 5 V, about 1 A, through its own USB power socket |
| ELEGOO camera | 5 V, about 0.5 A, through USB-C |

**About memory:** a bigger memory card does not give the Pi more working memory (RAM), which stays 512 MB. What the card can do is hold *swap*: when the 512 MB is full, the Pi moves things it is not using to the card. The setup script makes 1 GB of swap. This lets OG Browser run next to Quill.OS, but it is slower than real memory: expect pauses when switching between them, and expect LifeCraft and LifeGames (3D games) to run slowly or not at all on a Pi 3 A+.

Connect the battery pack to a **5 V step-down (buck) converter of 3 A or more**, and power all three parts from the converter's output. **Never connect the battery straight to the Pi.**

## 8. Using it

- Restart with `sudo reboot`. Quill.OS starts full screen.
- **The first start** (the Pi needs internet for it):
  1. **Sign in or sign up to Galau services.** This step cannot be skipped; it uses the same account as OG Browser and Galau Mail. Sign up creates a new name@gla.ml address, and its verification code arrives in Galau Mail.
  2. **Choose your display name** (it starts as your Galau username).
  3. **Choose a password for Quill** (at least 4 characters). You type it whenever Quill starts and to unlock the screen. It stays on the laptop and is separate from your Galau password.
  4. Pick a theme, and you are in.
- **Managing it in Loom:**
  - **Account:** change the display name, see which Galau account is signed in, **Switch account** or **Sign out**. Quill always needs an account, so after signing out it asks you to sign in again straight away.
  - **Security:** **Change password** (you type the current one first), plus auto-lock and lock now.
- **Keyboard:** see step 4 for what each special key does.
- **Turning off and on:** hold the padlock key (or the power button) for 2.5 seconds to shut down; press the power button to turn on (see step 5).
- **Trackpad:** works at the same time as touch. Click to click; a two-finger tap (or the trackpad's right button) opens menus; two-finger scrolling scrolls.
- **Touch:**
  - tap to click;
  - **press and hold** for the menus a right-click would open;
  - **drag a finger** up or down to scroll settings and lists.
- **Distance warning:** if you stay closer than 30 cm for about two seconds, the screen shows "Too close to the screen" until you move back. Change the distance, or turn the warning off, in **Loom → Eyes & camera**. That page also shows the distance live, which helps when testing the wiring.
- **Camera:** open **Iris** with Ctrl+K and type "Iris". Use **📸 Take photo** to save a picture in Pictures; Lens opens it.
- **OG Browser:** open it from the Spine or with Ctrl+K. It opens full screen in its own window:
  - **◀ Quill.OS** (top left) goes back to Quill.OS and keeps OG Browser open in the background;
  - **Show OG Browser** in its Quill window brings it back;
  - **✕ Close** ends it and frees its memory.

  Addresses ending in .og typed in Compass, Portal's sites and OG searches from the Inkwell all open in OG Browser. Sign-ins and saved data stay on the laptop.
- **XApps (the app store):**
  - **Discover** lists published apps; **Install** downloads one. It then appears in the Inkwell (Ctrl+K) and can be pinned to the Spine.
  - **Installed** lets you update or remove apps.
  - **Publish** shares your own apps. Sign in with your Galau account (only verified accounts can publish), make your app as one HTML file in Glyph, then press **New app**.
  - Apps run in their own window and cannot see the laptop's files.
- **Other computers:** run Quill.OS normally with `python3 quill.py`. The small-screen layout turns on by itself on screens up to 1024 pixels wide or 640 pixels high. You can force it with `--compact` and `--touch`, or turn it off with `--no-compact` and `--no-touch`.

## 9. If something does not work

| Problem | What to check |
|---|---|
| Black screen or wrong picture size | Check the HDMI cable. Some screens need settings in `/boot/firmware/config.txt`; follow the screen seller's instructions. |
| Touch does nothing | Check that the screen's touch USB cable is plugged into the Pi. |
| "Sensor not found" in Loom | Check the wiring in step 5 and that TRIG and ECHO are not swapped. |
| Distance always "—" | ECHO is not getting through: check the resistors and the GND wire. |
| Iris: "The camera is not answering" | Check that the camera has power and that the Pi is connected to the ELEGOO-… network (`nmcli dev status`). |
| OG Browser or an XApp: "cannot start here" | The web engine is missing: run `sh pi/install.sh` again while connected to the internet. |
| OG Browser: "could not connect" | The Pi has no internet; it may be on the camera's network (see step 6). |
| A special key does nothing | Open **Loom → Keyboard** and press the key: if it shows a plain name such as F4, choose **Give this key an action**. If the keyboard key (F5) never shows up, check that `python3-evdev` is installed (run `sh pi/install.sh` again). |
| Holding the padlock key does not shut down | Check that Quill.OS was started full screen by the setup script (on other computers holding it only shows Quill's own "off" screen). If it says it could not be turned off, run `sh pi/install.sh` again. |
| The power button does not turn the Pi on | Check that it is wired to pin 5 and a GND pin (not pin 3 or 4), and that the battery is still connected. |
| Wrong characters (no Ç) | Choose **Portuguese (Portugal)** in **Loom → Keyboard → Layout**. |
| Trackpad or touch stops working | Check the USB hub's cable to the Pi. If the hub has a power socket, power it from the 5 V converter. |
| Stuck on "Sign in to Galau services" | The Pi needs internet for this step: connect it to your home Wi-Fi (see step 6). |
| Forgot Quill's password | Over SSH, open `~/.local/share/quill-os/state.json`, change the `"pin"` value inside `"user"` to `""` and restart Quill; then set a new one in Loom → Security. |
| Quill.OS closes with an error | Read `~/.quill-x.log`, or run `python3 quill.py` over SSH with `DISPLAY=:0` to see the message. |
