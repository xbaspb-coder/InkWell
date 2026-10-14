# Building Inkwell: setup and wiring

Inkwell is made of these parts:
- a Raspberry Pi 3 Model A+, which runs Quill.OS;
- a 7-inch HDMI touchscreen;
- a Bluetooth keyboard;
- an HC-SR04 distance sensor (the "eyes"), which warns when someone sits too close to the screen;
- the ELEGOO ESP32 camera module, used by the Iris camera app.

## 1. Parts list

| Part | Notes |
|---|---|
| Raspberry Pi 3 Model A+ | Runs Quill.OS |
| microSD card, 16–32 GB | Holds the operating system |
| 7-inch HDMI touchscreen | Picture through HDMI, touch through USB |
| Bluetooth keyboard | The Pi's only USB port is used by the touchscreen |
| HC-SR04 distance sensor | Wired to the Pi's GPIO pins |
| Resistors: one 1 kΩ, one 2 kΩ | Protect the Pi from the sensor's 5 V signal |
| ELEGOO ESP32 camera module | Powered through its USB-C socket |
| Battery pack and 5 V step-down converter (3 A or more) | Powers the Pi, the screen and the camera |
| Breadboard and jumper wires | For the sensor wiring |

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
- turns on automatic login;
- makes Quill.OS start full screen every time the Pi powers on.

## 4. Pair the Bluetooth keyboard

Put the keyboard in pairing mode (see its manual), then on the Pi type:

```sh
bluetoothctl
power on
agent on
scan on
```

Wait until the keyboard's name appears with an address such as `AA:BB:CC:DD:EE:FF`. Then type the following, using your keyboard's address, and enter any code it shows on the Bluetooth keyboard:

```sh
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF
quit
```

`trust` makes the keyboard reconnect by itself after every restart.

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

3. The Pi has only one Wi-Fi radio. While it is connected to the camera, it has **no internet**. Install software (step 3) while it is still on your home Wi-Fi.

Quill.OS looks for the camera at `http://192.168.4.1`, which is the ELEGOO camera's usual address. You can change it in **Loom → Eyes & camera**.

## 7. Power

| Part | Needs |
|---|---|
| Raspberry Pi 3 A+ | 5 V, up to 2.5 A, through its micro-USB power socket |
| 7-inch screen | 5 V, about 1 A, through its own USB power socket |
| ELEGOO camera | 5 V, about 0.5 A, through USB-C |

Connect the battery pack to a **5 V step-down (buck) converter of 3 A or more**, and power all three parts from the converter's output. **Never connect the battery straight to the Pi.**

## 8. Using it

- Restart with `sudo reboot`. Quill.OS starts full screen.
- **Touch:**
  - tap to click;
  - **press and hold** for the menus a right-click would open;
  - **drag a finger** up or down to scroll settings and lists.
- **Distance warning:** if you stay closer than 30 cm for about two seconds, the screen shows "Too close to the screen" until you move back. Change the distance, or turn the warning off, in **Loom → Eyes & camera**. That page also shows the distance live, which helps when testing the wiring.
- **Camera:** open **Iris** with Ctrl+K and type "Iris". Use **📸 Take photo** to save a picture in Pictures; Lens opens it.
- **Other computers:** run Quill.OS normally with `python3 quill.py`. The small-screen layout turns on by itself on screens up to 1024 pixels wide or 640 pixels high. You can force it with `--compact` and `--touch`, or turn it off with `--no-compact` and `--no-touch`.

## 9. If something does not work

| Problem | What to check |
|---|---|
| Black screen or wrong picture size | Check the HDMI cable. Some screens need settings in `/boot/firmware/config.txt`; follow the screen seller's instructions. |
| Touch does nothing | Check that the screen's touch USB cable is plugged into the Pi. |
| "Sensor not found" in Loom | Check the wiring in step 5 and that TRIG and ECHO are not swapped. |
| Distance always "—" | ECHO is not getting through: check the resistors and the GND wire. |
| Iris: "The camera is not answering" | Check that the camera has power and that the Pi is connected to the ELEGOO-… network (`nmcli dev status`). |
| Quill.OS closes with an error | Read `~/.quill-x.log`, or run `python3 quill.py` over SSH with `DISPLAY=:0` to see the message. |
