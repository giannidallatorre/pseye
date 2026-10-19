# pseye-macos

> **Fighting obsolescence, one USB device at a time.** The PS Eye shipped in
> 2007; this keeps it a first-class webcam on a 2026 Mac, because good hardware
> should not become e-waste just because the drivers stopped.

Use a **Sony PlayStation Eye** (PS3) as a normal system webcam on macOS —
no kernel extension, no signed driver, no Apple Developer account.

The PS Eye is not a UVC camera, so macOS never registers it as a webcam and Zoom
or Meet will not list it. This project reads it in user space over **libusb**
(via [pseyepy](https://github.com/bensondaled/pseyepy)) and pushes the frames
into the **OBS Virtual Camera** Camera Extension with
[pyvirtualcam](https://github.com/letmaik/pyvirtualcam). OBS must be installed
and its virtual camera activated once, but **OBS does not need to be running**.

Tested on macOS 26.7.1 (Tahoe) on an **Intel** Mac with libusb 1.0.30. Nothing
here is architecture-specific (pseyepy builds a universal x86_64/arm64 binary),
so Apple Silicon should work too, but it has not been tested there.

## Requirements

- macOS 13 or later — pyvirtualcam drives the OBS Camera Extension through
  `CMIOExtension`, which it selects from macOS 13 (Darwin 22) onwards
- [OBS Studio](https://obsproject.com/) installed, with its virtual camera
  activated once (see below)
- `libusb` (`brew install libusb`)
- Python 3.12 to 3.14 — required by pyvirtualcam and numpy

## Install

```bash
brew install libusb
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then activate the OBS virtual camera **once**:

1. Open OBS → bottom right, `Start Virtual Camera`, then `Stop Virtual Camera`.
2. Quit OBS.

From then on the system webcam `OBS Virtual Camera` stays registered and this
project can feed it without OBS running.

## Usage

```bash
./pseye on        # start the system webcam (background, logs to vcam.log)
./pseye off       # stop it
./pseye toggle    # flip the current state
./pseye status    # show state: ON / ON (no frames) / OFF
```

Run `./pseye -h` for all commands and the options accepted by `on`/`toggle`.

`status` reports `ON (no frames)` when the process is alive but the camera is
not delivering frames — for example when the USB link has fallen back to full
speed. `pseye on` waits for the first frame before reporting success, and
`pseye off` escalates to `SIGKILL` if a stuck process ignores `SIGTERM`.

Then in Zoom: **Video** → `OBS Virtual Camera`, **Microphone** →
`USB Camera-B4.09.24.1`.

For a foreground run, use `./vcam.sh` (Ctrl-C to stop); add `--stats 5` for live fps stats.

### Options

```bash
./pseye on --fps 30                            # less USB bandwidth / less CPU
./pseye on --gray                              # grayscale (1/3 of the data)
./pseye on --width 320 --height 240 --fps 125  # slow motion
./pseye on --no-auto-gain --gain 40            # manual gain (0-63)
./pseye on --exposure 200                      # manual exposure (0-255)
./pseye on --no-auto-wb --red 140 --blue 150   # manual white balance
./pseye on --flip-h                            # mirror (or --flip-v)
```

Defaults: 640x480 @ 60 fps, colour, auto gain and auto white balance on. The
camera does 640x480 @ 60 fps natively and up to 125 fps at 320x240; `--fps` is
rounded down to the nearest rate the camera supports (e.g. `--fps 120` gives
100 fps).

`auto_exposure` is unreliable in this driver (it aborts the process on some
starts) and is therefore opt-in via `--auto-exposure`.

### Auto-start on plug-in

```bash
./pseye install     # LaunchAgent: start the webcam when the PS Eye is plugged in
./pseye uninstall   # remove it
```

`install` writes `~/Library/LaunchAgents/com.pseye.watch.plist` and bootstraps
it into your GUI session. The agent runs `./pseye watch` every 5 seconds, which
starts the webcam when the camera is present and stops it (turning the LED off)
when it is unplugged. It stays idle while `./pseye off` is in effect; `./pseye on`
clears that.

The plist contains the absolute path of this directory, so re-run
`./pseye install` if you move the folder.

### Uninstall

```bash
./pseye off            # stop the webcam (also turns the LED off)
./pseye uninstall      # remove the LaunchAgent
rm -rf .venv           # remove the virtualenv
rm -f vcam.log .paused # remove runtime state
```

Nothing is installed system-wide: no kext, no DAL plugin, no files outside this
directory and `~/Library/LaunchAgents/`. The only system-wide component is the
OBS Virtual Camera Camera Extension, which belongs to OBS.

`libusb` is a normal Homebrew package and is left in place; remove it with
`brew uninstall libusb` if nothing else on the machine needs it.

## Two PS Eyes at once

Each camera is served by a separate process, on a different port, with `--index`
selecting the camera (0-based):

```bash
./start.sh --index 0 --port 8090   # first PS Eye
./start.sh --index 1 --port 8091   # second PS Eye
```

In OBS add two Browser Sources, one per port, and compose them in a scene.

Two caveats:

- **USB bandwidth.** Two PS Eyes at 640x480 @ 60 fps on the same USB 2.0
  controller can saturate the bus (one camera at VGA/60 already uses ~30-40 MB/s).
  If one stutters, use `--res qvga` or `--fps 30` on it, or plug the cameras into
  different USB controllers.
- **Single output.** `OBS Virtual Camera` is one webcam, so the two cameras are
  composited into a single stream. Two independently selectable webcams require
  NDI Virtual Input.

## Alternative mode: MJPEG server

Instead of feeding the virtual camera directly, the frames can be served over
HTTP as MJPEG and consumed by an OBS Browser Source. This is useful when you want
OBS to do the compositing.

```bash
./start.sh                      # http://localhost:8090, 30 fps, VGA
./start.sh --res qvga --fps 60  # 320x240 @ 60 fps
./start.sh --quality 90         # sharper JPEG
./start.sh --port 8091          # different port
```

In OBS: `+` → **Browser** → URL `http://localhost:8090`, then
`Start Virtual Camera`. Stop the server with Ctrl-C or `pkill -f mjpeg_server.py`.

## How it works

```
PS3 Eye ──libusb──> pseyepy ──> vcam.py ──pyvirtualcam──> OBS Virtual Camera
                                                                    │
                                                                    ▼
                                                          Zoom / Meet / ...
```

The PS Eye (VID:PID `1415:2000`, OV534 bridge, OV7720/OV7725 sensor) speaks a
proprietary Sony protocol, not UVC. macOS therefore never registers it in
CoreMediaIO/AVFoundation, and applications only see cameras registered there.
Reading it over libusb gives you *capture*, not a *webcam* — the bridge to a
system-wide webcam is the OBS Camera Extension, which pyvirtualcam drives
directly through its `obs_cmioextension` backend.

Two consequences worth knowing:

- The OBS Camera Extension advertises a single mode, **1920x1080 @ 60**, but it
  does not upscale: it forwards the buffer pyvirtualcam sends, so a 640x480
  client produces 640x480 frames (measured with ffmpeg). The only conversion is
  RGB→UYVY, done in C by `libyuv` inside pyvirtualcam.
- The PS Eye's **4-microphone array** is a standard USB Audio Class device and
  macOS exposes it natively as `USB Camera-B4.09.24.1` (4 channels, 16 kHz). No
  driver needed; select it directly in Zoom or route it through OBS.

## Notes and limitations

- **The LED.** The LED is driven by the camera's own registers
  (`PS3EYECam::start()` sets it, `PS3EYECam::stop()` clears it), and `stop()` is
  only reached through `Camera.end()`. `vcam.py` cannot call `end()` (see below),
  so `./pseye off` runs `led_off.py` in a separate process afterwards to turn the
  LED off.
- **`Camera.end()` aborts the process.** PS3EYEDriver's teardown calls
  `libusb_cancel_transfer()` on transfers it has already freed, which trips a
  libusb assertion (`Abort trap: 6`). Measured: 5 crashes out of 8 shutdowns with
  pyvirtualcam running, 0 out of 15 without it. `vcam.py` therefore exits with
  `os._exit(0)`, which also skips pseyepy's `atexit` handler. The kernel releases
  the USB interface when the process dies and the next start works normally. A
  fix for the driver is in [`patches/`](patches/).
- **Zoom caches the camera list** at launch: restart Zoom after changing which
  cameras are available.
- **`vcam.sh` refuses to start** if another process already holds the camera's
  video interface (it checks `UsbExclusiveOwner` on `IOUSBHostInterface@0` via
  `ioreg`). This avoids the segfault pseyepy hits when the device is already open.
- The PS Eye has a **single sensor**; it is not a stereo camera. `cam_count()`
  returns 1 per device. True stereo needs two cameras plus calibration.
- `libusb: darwin_reenumerate_device ... not opened for exclusive access` on
  close is a harmless known warning.

## Troubleshooting

| Symptom | Cause / remedy |
|---|---|
| `vcam.sh`: *the PS Eye is already in use* | another process holds it → `pkill -f mjpeg_server.py` (or `pkill -f vcam.py`) |
| `status` says `ON (no frames)` | the USB link fell back to full speed (12 Mbps): check `UsbLinkSpeed` in `ioreg -w0 -l -r -n "USB Camera-B4.09.24.1"` (it must be `480000000`) and plug the camera directly into the Mac, not into a hub |
| Zoom does not see `OBS Virtual Camera` | the OBS virtual camera was never activated: open OBS → *Start Virtual Camera* → *Stop* → quit |
| `pyvirtualcam`: *OBS Virtual Camera is not installed* | same as above: OBS must be installed and its virtual camera activated once |
| Zoom does not see the webcam you just started | Zoom caches the camera list: restart Zoom |
| OBS Browser Source is black | server not running → `lsof -nP -iTCP:8090 -sTCP:LISTEN`; or right-click the source → *Refresh* |
| No audio in Zoom | wrong microphone: pick `USB Camera-B4.09.24.1` |
| Double audio / echo | both `Mic/Aux` (system mic) and the PS Eye are active: pick one |
| Stuttering video | lower `--quality`, or switch to `--res qvga` / `--fps 30` |
| Two PS Eyes: the second will not open, or one stutters | USB 2.0 bandwidth saturated: see *Two PS Eyes at once* |
| `--index 1` → *No camera available at index 1* | index does not exist: start without `--index` and read `Connected PS3 Eye cameras: N` |
| Microphone permission denied | *System Settings → Privacy & Security → Microphone* → enable Zoom/OBS |

## Verifying it works

```bash
# grab a frame from the system webcam and check it is not black
IDX=$(ffmpeg -f avfoundation -list_devices true -i "" 2>&1 | grep "OBS Virtual Camera" | sed -E 's/.*\[([0-9]+)\].*/\1/')
ffmpeg -y -f avfoundation -framerate 60 -video_size 1920x1080 -i "${IDX}:none" -frames:v 1 -update 1 /tmp/cap.png
.venv/bin/python -c "from PIL import Image; import numpy as np; a=np.asarray(Image.open('/tmp/cap.png').convert('RGB')); print('mean', a.reshape(-1,3).mean(0).round(1), 'std', a.reshape(-1,3).std(0).round(1))"

# MJPEG mode: count JPEG frames in 3 seconds
curl -s --max-time 3 http://localhost:8090/stream -o /tmp/t.bin && \
  python3 -c "d=open('/tmp/t.bin','rb').read(); print('frames:', d.count(b'\xff\xd8\xff'))"

# audio: record 3 s from the PS Eye microphone and measure the level
AUDIO=$(ffmpeg -f avfoundation -list_devices true -i "" 2>&1 | grep "USB Camera-B4.09.24.1" | sed -E 's/.*\[([0-9]+)\].*/\1/')
ffmpeg -f avfoundation -i ":${AUDIO}" -t 3 -ac 1 -ar 16000 -y /tmp/a.wav && \
  ffmpeg -i /tmp/a.wav -af volumedetect -f null - 2>&1 | grep volume
```

## Files

| File | Purpose |
|---|---|
| `pseye` | Control command: `on` / `off` / `toggle` / `status` / `install` / `uninstall` |
| `vcam.py` | PS Eye → system webcam via pyvirtualcam |
| `vcam.sh` | Convenience launcher for `vcam.py`, with the in-use guard |
| `led_off.py` | Turns the camera LED off; run by `pseye off` |
| `mjpeg_server.py` | MJPEG server for an OBS Browser Source; `--index N` selects the camera |
| `start.sh` | Convenience launcher for the MJPEG server |
| `requirements.txt` | Pinned Python dependencies (pseyepy from fork, pyvirtualcam, Pillow, NumPy) |
| `patches/` | Fixes for the PS3EYEDriver teardown crash (upstream and pseyepy) |

## License

GPL-2.0 — see [`LICENSE`](LICENSE). This project imports pyvirtualcam, which is
GPL-2.0, so it is a derivative work. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the licenses of everything
it builds on, including the MIT/GPL-2.0 split of PS3EYEDriver.

### Legal notes

This project does **not** redistribute OBS Studio or its Camera Extension. It
uses the extension that OBS installs, through Apple's public `CMIOExtension`
framework: the extension exposes a *sink* stream and authorises any client, which
is exactly how OBS itself feeds it. Nothing is patched, re-signed or bypassed —
the extension is activated once through System Settings, as Apple requires.

The PS Eye protocol is proprietary and undocumented by Sony; the reverse
engineering was done by the authors of PS3EYEDriver and pseyepy, whose code has
been public for well over a decade. This project only uses their work.

*This is a technical reading of the licenses involved, not legal advice.*

## Credits

- [inspirit/PS3EYEDriver](https://github.com/inspirit/PS3EYEDriver) — the C driver
- [bensondaled/pseyepy](https://github.com/bensondaled/pseyepy) — the Python wrapper
- [letmaik/pyvirtualcam](https://github.com/letmaik/pyvirtualcam) — the virtual camera bridge
- [libusb](https://github.com/libusb/libusb) — USB access
- [OBS Studio](https://obsproject.com/) — the signed Camera Extension
