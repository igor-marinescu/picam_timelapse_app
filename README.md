# picam_timelapse_app

A Python + Flask web application for a **Raspberry Pi Zero** with a **Raspberry Pi
Camera**, built for shooting timelapse photo sequences on a device with no display
and no viewfinder.

Because the Pi has no screen, everything is driven from a web interface you open on
a phone or laptop on the same network. The live-streaming page acts as the
viewfinder so you can focus the lens and check the optical settings before starting
a run.

Photos are written to a local folder with a timestamp filename. Assembling them into
a video is deliberately **not** part of this application — see
[Turning the photos into a video](#turning-the-photos-into-a-video) for the one-liner
you can run afterwards on a desktop machine.

---

## Table of contents

- [Features](#features)
- [How it works: the three states](#how-it-works-the-three-states)
- [Screens](#screens)
- [Camera settings](#camera-settings)
- [Hardware requirements](#hardware-requirements)
- [Deploying on a Raspberry Pi](#deploying-on-a-raspberry-pi)
  - [1. Install Raspberry Pi OS](#1-install-raspberry-pi-os)
  - [2. Enable and test the camera](#2-enable-and-test-the-camera)
  - [3. Install the system packages](#3-install-the-system-packages)
  - [4. Get the application onto the Pi](#4-get-the-application-onto-the-pi)
  - [5. Create the virtual environment](#5-create-the-virtual-environment)
  - [6. First run](#6-first-run)
  - [7. Run it as a service](#7-run-it-as-a-service)
- [Configuration](#configuration)
- [Where the photos go](#where-the-photos-go)
- [Turning the photos into a video](#turning-the-photos-into-a-video)
- [Running on a desktop without a camera](#running-on-a-desktop-without-a-camera)
- [HTTP API](#http-api)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [Notes on Pi Zero performance](#notes-on-pi-zero-performance)
- [Security](#security)

---

## Features

- **Live MJPEG streaming** to use the browser as a viewfinder while focusing the lens.
- **Configurable timelapse interval**, from 1 second to 24 hours.
- **Camera controls**: exposure time, analogue gain, white balance, colour saturation
  and sharpness — changed from the browser, persisted across reboots.
- **Photos saved with timestamp filenames** (`YYYYMMDD_HHMMSS.jpg`) to a local folder.
- **Live progress page**: photo count, elapsed time, configured interval, countdown to
  the next shot, and a button to view the most recent photo.
- **Runs headless as a systemd service**, starting automatically at boot.
- Settings are written atomically, so a power cut mid-write cannot corrupt them.
- Works with **multiple browsers at once**: every page polls the device state, and any
  browser showing a stale page is redirected to the page for the actual current state.

## How it works: the three states

The application is always in exactly one of three states, and each state has one
web page:

| State | Page | What is happening |
|---|---|---|
| **Idle** | `/settings` — *Settings and Control* | Camera released, nothing running. |
| **Timelapse** | `/timelapse` — *Timelapse Process* | Photos being captured at the configured interval. |
| **Streaming** | `/stream` — *Video Live Streaming* | MJPEG live view running. |

```
                   Start timelapse
        ┌────────────────────────────────────►┌─────────────┐
        │                                     │  TIMELAPSE  │
        │      ◄────────────────────────────  └─────────────┘
 ┌──────┴───┐        Stop timelapse
 │   IDLE   │
 └──────┬───┘        Stop streaming
        │      ◄────────────────────────────  ┌─────────────┐
        │                                     │  STREAMING  │
        └────────────────────────────────────►└─────────────┘
                   Start streaming
```

Timelapse and streaming are **mutually exclusive** — the Pi camera can only be
configured for one use case at a time, so you must return to Idle to switch. Trying
to start one while the other is running returns HTTP 409 with an explanatory message
rather than crashing the camera stack. The camera is fully released while Idle,
which matters on a Pi Zero where memory is scarce.

Opening `/` always redirects to the page for the current state, so a bookmark to the
root URL is always correct.

## Screens

**Settings and Control** (Idle) — configure the interval and all camera settings, then
either start the timelapse or start the live stream. Both buttons save the form first,
so you can never start a multi-hour run with an interval you thought you had changed.

**Timelapse Process** — shows photos taken, elapsed time, the configured interval and
a countdown to the next photo, plus the last photo's filename and the failed-capture
count. *Show last picture* loads the most recent photo; if you leave it open it
refreshes itself as new photos arrive. *Stop timelapse* returns to Idle.

**Video Live Streaming** — full-width live image from the camera, a summary of the
settings in effect, a *Reload the live image* button (for when a phone suspends the
connection), and *Stop live streaming* to return to Idle.

The timelapse keeps running whether or not a browser is open — closing the phone or
letting the screen lock does not stop a run. Only pressing *Stop* does.

## Camera settings

All values are validated and clamped server-side, so a bad entry can never reach the
camera stack. An invalid value leaves the previous setting untouched.

| Setting | Range | libcamera control | Notes |
|---|---|---|---|
| Interval | 1 – 86400 s | — | Seconds between photos. |
| Automatic exposure | on / off | `AeEnable` | When on, the sensor picks both exposure time and gain. |
| Exposure time | 100 – 10 000 000 µs | `ExposureTime` | Only used when automatic exposure is off. |
| Gain | 1.0 – 16.0 | `AnalogueGain` | Analogue (ISO-like) gain. Only used when automatic exposure is off. |
| White balance | auto, incandescent, tungsten, fluorescent, indoor, daylight, cloudy, manual | `AwbMode` / `ColourGains` | *Manual* uses the red/blue gains below. |
| Red / blue gain | 0.1 – 8.0 | `ColourGains` | Only used when white balance is *manual*. |
| Colour saturation | 0.0 – 32.0 | `Saturation` | 1.0 = normal, 0.0 = greyscale. |
| Sharpness | 0.0 – 16.0 | `Sharpness` | 1.0 = normal, 0.0 = no sharpening. |

Exposure time and gain are grouped under one *Automatic exposure* toggle because that
is how the sensor works: the AEC/AGC algorithm sets both together, so you cannot fix
one and auto the other. Fields the camera will ignore are greyed out in the form, but
their values are still saved — switching back to manual restores what you typed.

**Tuning tip:** start the live stream, change a setting, press *Save settings*, and
the running stream is retuned immediately so you can see the effect in the viewfinder.
Then stop the stream and start the timelapse with those settings.

Settings persist in `settings.json` next to the application, so they survive a
restart of the service and of the Pi.

## Hardware requirements

- **Raspberry Pi Zero, Zero W, Zero 2 W**, or any other Raspberry Pi.
- A **Raspberry Pi Camera Module** (v1, v2, v3, HQ, or a compatible libcamera sensor)
  and the correct ribbon cable — the Pi Zero family uses the **narrower** cable, not
  the one that ships with full-size Pi camera kits.
- A microSD card with **Raspberry Pi OS Bullseye or newer** (Bookworm recommended).
  Picamera2 and libcamera are not available on the older Buster releases.
- Network connectivity (Wi-Fi on the Zero W / Zero 2 W, or a USB Ethernet adapter).
- Enough free space on the card for the run: budget roughly 2–5 MB per photo at full
  still resolution.

## Deploying on a Raspberry Pi

The commands below assume the default `pi` user and a home directory of `/home/pi`.
Adjust the paths if your username differs.

### 1. Install Raspberry Pi OS

Flash Raspberry Pi OS with the [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
In the Imager, open the settings gear (⚙) **before** writing and pre-configure:

- hostname, e.g. `picam`
- **enable SSH**
- username and password
- Wi-Fi SSID, password and country

That gives you a headless Pi you can reach without ever attaching a screen.

For a Pi Zero / Zero W, choose **Raspberry Pi OS (Legacy, 32-bit) Bullseye** or the
32-bit Bookworm image — the original Zero is ARMv6 and cannot run the 64-bit images.
A Pi Zero 2 W runs the 32-bit or 64-bit image.

Boot the Pi, then log in:

```bash
ssh pi@picam.local
```

### 2. Enable and test the camera

On Bookworm and current Bullseye images the camera is auto-detected and no
`raspi-config` step is needed. Confirm the camera is seen:

```bash
# Bookworm and later
rpicam-hello --list-cameras

# Bullseye (older name for the same tool)
libcamera-hello --list-cameras
```

You should see your sensor listed (for example `imx219` for a Camera Module v2). If
you get *no cameras available*, see [Troubleshooting](#troubleshooting) before going
any further — nothing else will work until this command succeeds.

### 3. Install the system packages

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y python3-picamera2 python3-venv python3-pip git
```

> **Important:** `picamera2` must come from `apt`, **not** `pip`. The apt package is
> built against the system's libcamera and pulls in the matching native bindings;
> `pip install picamera2` either fails to build or produces a binding that cannot
> talk to your libcamera. This is why `picamera2` is not in `requirements.txt`.

On a minimal (Lite) image, `python3-picamera2` pulls in a large dependency tree. If
you want to avoid the GUI preview dependencies:

```bash
sudo apt install -y --no-install-recommends python3-picamera2
```

Make sure your user is in the `video` group (the default `pi` user already is):

```bash
sudo usermod -aG video "$USER"    # log out and back in for this to take effect
```

### 4. Get the application onto the Pi

Either clone it:

```bash
cd ~
git clone <your-repository-url> picam_timelapse_app
cd picam_timelapse_app
```

…or copy it from your workstation:

```bash
# run this on your PC, not on the Pi
rsync -av --exclude .venv --exclude photos ./picam_timelapse_app/ pi@picam.local:~/picam_timelapse_app/
```

### 5. Create the virtual environment

The virtual environment **must** be created with `--system-site-packages` so that the
apt-installed `picamera2` and `libcamera` bindings remain visible inside it:

```bash
cd ~/picam_timelapse_app
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Verify that the real camera library is visible from inside the venv:

```bash
.venv/bin/python -c "import picamera2; print('picamera2 OK')"
```

If that prints an `ImportError`, the venv was created without
`--system-site-packages`. Delete `.venv` and redo this step — otherwise the
application starts anyway but runs with its built-in **mock camera** and saves
generated test images instead of photos.

### 6. First run

```bash
cd ~/picam_timelapse_app
.venv/bin/python app.py
```

The log prints the photo directory and the settings file, and warns loudly if it
fell back to the mock camera. Now open the interface from your phone or laptop:

```
http://picam.local:8000/
```

or use the Pi's IP address (`hostname -I` on the Pi) if `.local` name resolution does
not work on your network:

```
http://192.168.1.42:8000/
```

Press Ctrl+C to stop. `python app.py` runs Flask's development server, which is fine
for a first test — the next step switches to a production server.

### 7. Run it as a service

Running under systemd means the app starts at boot, restarts if it crashes, and keeps
running after you close your SSH session. It also uses **waitress** instead of the
Flask development server.

A ready-made unit file is included as `picam-timelapse.service`:

```bash
sudo cp ~/picam_timelapse_app/picam-timelapse.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now picam-timelapse
```

Check that it came up:

```bash
systemctl status picam-timelapse
journalctl -u picam-timelapse -f      # live log, Ctrl+C to stop watching
```

If you did not clone to `/home/pi/picam_timelapse_app` or your user is not `pi`, edit
`User=`, `WorkingDirectory=` and the paths in `ExecStart=` in the unit file first.

Useful commands afterwards:

```bash
sudo systemctl restart picam-timelapse    # after changing the code
sudo systemctl stop picam-timelapse       # frees the camera for rpicam-hello
sudo systemctl disable picam-timelapse    # stop starting at boot
```

## Configuration

Everything the camera does is configured from the web interface. These environment
variables control the process itself:

| Variable | Default | Purpose |
|---|---|---|
| `PICAM_PHOTO_DIR` | `<app dir>/photos` | Where photos are written. |
| `PICAM_SETTINGS_FILE` | `<app dir>/settings.json` | Where settings are persisted. |
| `PICAM_HOST` | `0.0.0.0` | Bind address (`python app.py` only). |
| `PICAM_PORT` | `8000` | Port (`python app.py` only). |
| `PICAM_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, … |

Under systemd, set these with `Environment=` lines in the unit file; the port is set
by the `--port` flag on the `waitress-serve` command in `ExecStart=`.

To write photos to a USB stick instead of the SD card — worth doing for long runs,
both for space and to spare the card's write endurance — mount it and point
`PICAM_PHOTO_DIR` at it:

```ini
Environment=PICAM_PHOTO_DIR=/media/usb/timelapse
```

Make sure the service user can write there, and that the stick is mounted before the
service starts (add a `RequiresMountsFor=` line to the unit).

## Where the photos go

Photos land in the photo directory as `YYYYMMDD_HHMMSS.jpg`, in the Pi's local
timezone:

```
photos/
├── 20260906_114728.jpg
├── 20260906_114730.jpg
└── 20260906_114732.jpg
```

The name sorts chronologically as plain text, which is exactly what `ffmpeg`'s glob
input pattern needs. If two photos would land in the same second (possible with a
1-second interval), a `_01`, `_02`, … counter is appended so nothing is overwritten.

Set the Pi's timezone before a run, or the filenames will not match local time:

```bash
sudo timedatectl set-timezone Europe/Berlin
```

Copy the photos off with `scp` or `rsync`:

```bash
# run this on your PC
rsync -av pi@picam.local:~/picam_timelapse_app/photos/ ./my-timelapse/
```

## Turning the photos into a video

Out of scope for the application, but this is the command you want — run it on a
desktop machine, not on the Pi:

```bash
# 24 fps, H.264, scaled to 1080p
ffmpeg -framerate 24 -pattern_type glob -i 'my-timelapse/*.jpg' \
       -vf "scale=1920:-2" -c:v libx264 -crf 20 -pix_fmt yuv420p timelapse.mp4
```

## Running on a desktop without a camera

If `picamera2` cannot be imported, the application automatically falls back to a
**mock camera** that produces generated test images with a timestamp and frame
counter burned in. This lets you develop and test the whole web interface on a
Windows/macOS/Linux machine:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pillow      # optional: nicer generated test images
.venv/bin/python app.py
```

Every page shows an orange **MOCK CAMERA** badge in the header, and the startup log
warns about it, so there is no way to mistake test images for real photos. Without
Pillow the mock still works, but every frame is the same tiny placeholder JPEG.

## HTTP API

The pages are thin clients over this API. It is handy for scripting a run or for
checking on the device from elsewhere.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/status` | Current state, photo count, elapsed time, last photo, last error. |
| `GET` | `/api/settings` | Current settings. |
| `POST` | `/api/settings` | Update settings (JSON body or form post). Returns the stored, clamped values. |
| `POST` | `/api/timelapse/start` | Idle → Timelapse. |
| `POST` | `/api/timelapse/stop` | Timelapse → Idle. |
| `POST` | `/api/stream/start` | Idle → Streaming. |
| `POST` | `/api/stream/stop` | Streaming → Idle. |
| `GET` | `/video_feed` | MJPEG stream. Only valid while streaming. |
| `GET` | `/api/last_photo` | Redirects to the most recent photo of the current run. |
| `GET` | `/photos/<name>` | Serve one photo. |

Invalid transitions return **409** with an `error` message; camera failures return
**500**. Both include the current `status` so a client can resynchronise.

```bash
# Take a photo every 5 minutes for as long as it takes
curl -X POST http://picam.local:8000/api/settings \
     -H 'Content-Type: application/json' -d '{"interval_seconds": 300}'
curl -X POST http://picam.local:8000/api/timelapse/start

curl -s http://picam.local:8000/api/status
curl -X POST http://picam.local:8000/api/timelapse/stop
```

## Project layout

```
picam_timelapse_app/
├── app.py                    # Flask routes, state-machine page routing, API
├── camera_manager.py         # Camera ownership, state machine, capture worker
├── settings_store.py         # Validation, clamping, atomic JSON persistence
├── mock_picamera2.py         # Desktop stand-in for Picamera2
├── requirements.txt          # Flask + waitress (picamera2 comes from apt)
├── picam-timelapse.service   # systemd unit
├── templates/
│   ├── base.html
│   ├── settings.html         # "Settings and Control"
│   ├── timelapse.html        # "Timelapse Process"
│   └── stream.html           # "Video Live Streaming"
├── static/
│   ├── css/style.css         # Mobile-first, dark
│   └── js/
│       ├── common.js         # Status polling, state redirects, helpers
│       ├── settings.js
│       ├── timelapse.js
│       └── stream.js
├── photos/                   # Created at runtime (git-ignored)
└── settings.json             # Created at runtime (git-ignored)
```

`camera_manager.py` is the only module that touches the camera. All state transitions
are serialised through one re-entrant lock, so two browsers pressing buttons at the
same moment cannot leave the camera half-configured.

## Troubleshooting

**"no cameras available" from `rpicam-hello`**

- Power the Pi down completely before reseating the ribbon cable. The contacts face
  the board on the Pi Zero connector; the cable is easy to insert backwards.
- The Pi Zero family needs the **narrow** ribbon cable. The wide one from a
  full-size Pi kit will not fit.
- On a Camera Module v3 or a third-party sensor on older OS versions you may need an
  explicit overlay in `/boot/firmware/config.txt` (`/boot/config.txt` on Bullseye),
  e.g. `dtoverlay=imx708`. Reboot afterwards.
- Check `dmesg | grep -i imx` for whether the kernel probed the sensor at all.

**"Could not initialise the camera" in the web interface**

Something else already has the camera. The most common cause is the service running
while you also start `app.py` by hand, or a leftover `rpicam-hello`:

```bash
sudo systemctl stop picam-timelapse
sudo fuser -v /dev/video0        # who is holding the device
```

**The web interface shows an orange MOCK CAMERA badge**

`picamera2` is not importable from the environment the app is running in. Almost
always the venv was created without `--system-site-packages` — see
[step 5](#5-create-the-virtual-environment).

**The live stream is blank, or freezes after a while**

- Press *Reload the live image*. Phone browsers suspend long-lived connections when
  the screen locks or you switch apps, and MJPEG does not resume on its own.
- Only one or two viewers at a time on a Pi Zero. Each open viewfinder is a separate
  long-lived HTTP response competing for the same CPU.

**The interface is unreachable at `picam.local`**

mDNS is not available on every network. Use the IP address from `hostname -I`, and
check the port matches (`8000` by default).

**Photos are much darker or brighter than the live view**

The live stream and the still capture use different sensor modes, and with automatic
exposure the sensor re-converges when the mode changes. For consistent results across
a long run — and to stop the brightness flickering shot to shot — turn *Automatic
exposure* off and set the exposure time and gain explicitly.

**Failed captures counter is climbing**

Check `journalctl -u picam-timelapse` for the underlying error. The usual cause is a
full SD card (`df -h`) or a card that has gone read-only. Individual capture failures
are counted and logged but do not stop the run, so a transient problem does not lose
the rest of your timelapse.

## Notes on Pi Zero performance

The original Pi Zero / Zero W is a single-core ARMv6 machine, and it is the slowest
device this application is expected to run on. What that means in practice:

- **The live stream is a viewfinder, not video.** It runs at 640×480 and you should
  expect a handful of frames per second on a Zero W. That is enough to judge focus,
  which is what it is for. A Zero 2 W is noticeably smoother.
- **Keep the number of simultaneous viewers to one or two.** Every open viewfinder
  is another long-lived response to encode for.
- **Full-resolution stills take a couple of seconds** on a Zero W, including the SD
  card write. Intervals below about 5 seconds are unrealistic; the capture worker
  handles this correctly by skipping missed slots rather than firing back-to-back,
  so the run stays on schedule instead of drifting.
- **Long runs deserve a USB stick** for the photos, both for space and to spare the
  SD card's write endurance. See [Configuration](#configuration).
- The camera is released entirely while Idle, so the app's memory footprint between
  runs is just Python and Flask.

## Security

**There is no authentication.** Anyone who can reach the port can view the stream,
change the settings and start or stop a run. Keep the Pi on a trusted LAN.

If you need to reach it from outside your network, put it behind something that does
authentication — an SSH tunnel is the simplest:

```bash
# run this on your PC, then browse to http://localhost:8000/
ssh -L 8000:localhost:8000 pi@picam.local
```

Do not port-forward this application to the internet directly.
