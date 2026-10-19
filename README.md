# PSEye — PS3 Eye as a webcam on macOS

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
./pseye setup
```

That installs `libusb` with Homebrew (or lets pseyepy build its bundled copy
when Homebrew is missing, which needs the Xcode Command Line Tools), creates
`.venv` and installs the pinned dependencies. It is idempotent: run it again
after a `git pull`. At the end it trims the virtualenv — numpy's test suite and
`pip` are removed, which halves it (57 MB → 28 MB); a later `setup` puts `pip`
back with `ensurepip`.

The equivalent manual steps are:

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
./pseye on        # start the system webcam (background, logs to the state dir)
./pseye off       # stop it
./pseye toggle    # flip the current state
./pseye status    # show state: ON / ON (no frames) / OFF
./pseye doctor    # check python, libusb, camera, USB link, OBS extension
./pseye setup     # install libusb + the Python dependencies (idempotent)
./pseye uninstall # remove the virtualenv, auto-start and runtime files
```

Run `./pseye -h` for all commands and the options accepted by `on`/`toggle`.

`status` reports `ON (no frames)` when the process is alive but the camera is
not delivering frames — for example when the USB link has fallen back to full
speed. `pseye on` waits for the first frame before reporting success, and
`pseye off` escalates to `SIGKILL` if a stuck process ignores `SIGTERM`.

Both `status` and `doctor` print the USB link speed (`usb: 480 Mbps`); anything
other than 480 Mbps means the camera negotiated full speed and will not deliver
frames. `doctor` checks the whole chain and exits non-zero if something is
broken, so it is the first thing to run when the webcam does not work:

```
$ ./pseye doctor
python:      ok    /…/pseye/.venv/bin/python (3.14.8)
libusb:      ok    /usr/local/opt/libusb/lib/libusb-1.0.0.dylib
camera:      ok    plugged in
usb:         ok    480 Mbps
obs ext:     ok    active
webcam:      ok    ON
in use:      ok    pid 54620, Python (this webcam)
auto-start:  -     not installed
```

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

### Live image controls

The image controls can be changed while the webcam is running, without a
restart:

```bash
./pseye set gain 40          # manual gain (0-63), turns auto gain off
./pseye set exposure 200     # manual exposure (0-255), turns auto exposure off
./pseye set auto-wb off      # or on
./pseye set red 140          # manual white balance (0-255), turns auto WB off
./pseye set flip-h on        # or flip-v
./pseye set                  # show the current values
./pseye set reset            # back to the defaults
```

`pseye set` writes `.settings` in the state directory and sends `SIGHUP`;
`vcam.py` applies the new
values between frames, and they survive a restart. `--camera`, `--width`,
`--height`, `--fps` and `--gray` still need `pseye off` + `pseye on`, because
they change the USB stream or the virtual camera format.

`pseye set reset` restores the driver defaults (gain 20, exposure 128, neutral
balance, auto gain and auto WB on). Turning an auto mode back on also restores
those baseline values first, because the driver keeps the last manual registers
otherwise. `auto-exposure` is not available here: it is unstable in this driver
and stays opt-in via `--auto-exposure`.

If the neutral result of auto WB looks cold under warm indoor light, a slight
warm bias is `auto-wb off` with `blue 130` (red and green stay at 128); it
persists like any other setting.

### Auto-start on plug-in

```bash
./pseye autostart install   # LaunchAgent: start the webcam when the PS Eye is plugged in
./pseye autostart remove    # remove it
```

`autostart install` writes `~/Library/LaunchAgents/com.pseye.watch.plist` and
bootstraps it into your GUI session. The agent runs `./pseye watch` every 5
seconds, which starts the webcam when the camera is present and stops it
(turning the LED off) when it is unplugged. It stays idle while `./pseye off` is
in effect; `./pseye on` clears that, and so does `./pseye autostart install`,
since installing the auto-start means you want it to start by itself.

The plist contains the absolute path of this directory, so re-run
`./pseye autostart install` if you move the folder.

### Uninstall

```bash
./pseye uninstall      # asks for confirmation; -y to skip it
```

That stops the webcam, removes the LaunchAgent, deletes `.venv` and the state
directory (`~/Library/Application Support/pseye`: `vcam.log`, `.paused`,
`.heartbeat`, `.settings`). It leaves the
repository, `libusb` and the OBS Camera Extension alone: the first is yours, the
second is a normal Homebrew package (remove it with `brew uninstall libusb` if
nothing else needs it) and the third belongs to OBS.

Nothing is installed system-wide: no kext, no DAL plugin, no files outside this
directory, `~/Library/Application Support/pseye/` and `~/Library/LaunchAgents/`.

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

This mode is the only one that needs **Pillow**, which is therefore not in
`requirements.txt` (the virtual camera path does not use it):

```bash
.venv/bin/python -m ensurepip --upgrade   # setup trims pip from the venv
.venv/bin/python -m pip install Pillow
```

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
  only reached through `Camera.end()`. `vcam.py` calls `cam.end()` on the way
  out, so `./pseye off` turns the LED off and releases the USB interface.
- **`Camera.end()` used to abort the process.** PS3EYEDriver's teardown called
  `libusb_cancel_transfer()` on transfers it had already freed, which tripped a
  libusb assertion (`Abort trap: 6`): 5 crashes out of 8 shutdowns with
  pyvirtualcam running. The fix is in the pseyepy fork this project pins
  (`23624c2`, also in [`patches/`](patches/)); with it, 10 out of 10 on/off
  cycles are clean. `vcam.py` still exits with `os._exit(0)` so that shutdown
  can never hang.
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
| `status` says `ON (no frames)` | the USB link fell back to full speed (12 Mbps): `pseye status` / `pseye doctor` show the link speed; it must be 480 Mbps. Plug the camera directly into the Mac, not into a hub |
| Zoom does not see `OBS Virtual Camera` | the OBS virtual camera was never activated: open OBS → *Start Virtual Camera* → *Stop* → quit |
| `pyvirtualcam`: *OBS Virtual Camera is not installed* | same as above: OBS must be installed and its virtual camera activated once |
| Zoom does not see the webcam you just started | Zoom caches the camera list: restart Zoom |
| OBS Browser Source is black | server not running → `lsof -nP -iTCP:8090 -sTCP:LISTEN`; or right-click the source → *Refresh* |
| `mjpeg_server.py`: *needs Pillow* | `.venv/bin/python -m ensurepip --upgrade && .venv/bin/python -m pip install Pillow` (only the MJPEG mode uses it) |
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
| `pseye` | Control command: `on` / `off` / `toggle` / `status` / `doctor` / `setup` / `uninstall` / `set` / `autostart` |
| `vcam.py` | PS Eye → system webcam via pyvirtualcam |
| `vcam.sh` | Convenience launcher for `vcam.py`, with the in-use guard |
| `mjpeg_server.py` | MJPEG server for an OBS Browser Source; `--index N` selects the camera |
| `start.sh` | Convenience launcher for the MJPEG server |
| `requirements.txt` | Pinned Python dependencies (pseyepy from fork, pyvirtualcam, NumPy); Pillow only for the MJPEG server |
| `patches/` | Fixes for the PS3EYEDriver teardown crash (upstream and pseyepy) |
| `~/Library/Application Support/pseye/` | Runtime state, not code: `vcam.log`, `.settings`, `.heartbeat`, `.paused` (override with `PSEYE_STATE_DIR`) |

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
