# PSEye — PS3 Eye as a webcam on macOS

[![tests](https://github.com/giannidallatorre/pseye/actions/workflows/tests.yml/badge.svg)](https://github.com/giannidallatorre/pseye/actions/workflows/tests.yml)

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

Tested on macOS 26.7.1 (Tahoe) on an **Intel** Mac with libusb 1.0.30. CI
builds the driver and runs the suite on both Apple Silicon (`macos-latest`) and
Intel (`macos-15-intel`), so both architectures are covered at the build and
command-line level; the camera itself has only been exercised on Intel.

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
`pip` are removed, which halves it (57 MB → 27 MB); a later `setup` puts `pip`
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

`autostart install` writes `~/Library/LaunchAgents/com.pseye.agent.plist` and
bootstraps it into your GUI session. The agent runs `./pseye supervise` every 5
seconds; the supervisor starts the webcam when the camera is present and stops
it (turning the LED off) when it is unplugged. It stays idle while `./pseye off`
is in effect; `./pseye on` clears that, and so does `./pseye autostart install`,
since installing the auto-start means you want it to start by itself.

Unplugging is noticed within a couple of seconds, not when the heartbeat finally
goes stale: the supervisor checks the USB bus on every pass and kills `vcam.py`
at once. That matters because a `vcam.py` still blocked in `cam.read()` keeps
the device claimed, and re-plugging the PS Eye while it is claimed makes it
enumerate and drop off the bus again.

The supervisor stays alive for as long as the webcam runs, so launchd tracks the
process instead of losing it: at logout or shutdown it gets a `SIGTERM`, stops
`vcam.py` cleanly (`cam.end()`, transfers cancelled, LED off) and only escalates
to `SIGKILL` if the camera is stuck. It also watches the heartbeat, so a process
that is alive but no longer producing frames is restarted. With the agent
installed, `./pseye on` hands the process to the agent rather than starting an
untracked one, and `./pseye on --fps 30` keeps its options across restarts.

The plist contains the absolute path of this directory, so re-run
`./pseye autostart install` if you move the folder.

`autostart remove` only removes the agent: a webcam that is already running
keeps running (it says so), and `./pseye off` stops it. It also removes
everything the agent owns — the "paused" flag, the saved options and
`launchd.log` — so nothing is left behind.

### Uninstall

```bash
./pseye uninstall      # asks for confirmation; -y to skip it
```

That stops the webcam, removes the LaunchAgent, deletes `.venv` and the state
directory (`~/Library/Application Support/pseye`: `vcam.log`, `launchd.log`,
`.paused`, `.heartbeat`, `.settings`, `.args`). It leaves the
repository, `libusb` and the OBS Camera Extension alone: the first is yours, the
second is a normal Homebrew package (remove it with `brew uninstall libusb` if
nothing else needs it) and the third belongs to OBS.

Nothing is installed system-wide: no kext, no DAL plugin, no files outside this
directory, `~/Library/Application Support/pseye/` and `~/Library/LaunchAgents/`.

## Alternative mode: MJPEG server

The frames can also be served over HTTP as MJPEG for an OBS Browser Source,
which is useful when you want OBS to do the compositing, and it is the way to
run two PS Eyes at once. It needs Pillow, which the virtual camera path does
not. See [`docs/mjpeg.md`](docs/mjpeg.md).

## How it works

```
PS3 Eye ──libusb──> pseyepy ──> vcam.py ──pyvirtualcam──> OBS Virtual Camera
```

The PS Eye is not UVC, so macOS never registers it as a camera. This project
reads it in user space over libusb and feeds the OBS Camera Extension, which is
what applications see. The details — the 1920x1080 mode that does not upscale,
the microphone, the LED, the teardown crash, the warnings that are harmless —
are in [`docs/how-it-works.md`](docs/how-it-works.md).

## Troubleshooting

| Symptom | Cause / remedy |
|---|---|
| `vcam.sh`: *the PS Eye is already in use* | another process holds it → `pkill -f mjpeg_server.py`, or `./pseye off` for our own `vcam.py` |
| `status` says `ON (no frames)` | the USB link fell back to full speed (12 Mbps): `pseye status` / `pseye doctor` show the link speed; it must be 480 Mbps. Plug the camera directly into the Mac, not into a hub |
| `ON (no frames)` with the link at 480 Mbps | the camera stopped answering: the kernel log shows `status 0xe00002ed (transaction error)` on endpoint 0x81, which is `kIOReturnNotResponding`. Unplug and plug it back in — reopening it is not enough, the device stays wedged |
| Zoom does not see `OBS Virtual Camera` | the OBS virtual camera was never activated: open OBS → *Start Virtual Camera* → *Stop* → quit |
| `pyvirtualcam`: *OBS Virtual Camera is not installed* | same as above: OBS must be installed and its virtual camera activated once |
| Zoom does not see the webcam you just started | Zoom caches the camera list: restart Zoom |
| OBS Browser Source is black | server not running → `lsof -nP -iTCP:8090 -sTCP:LISTEN`; or right-click the source → *Refresh* |
| `mjpeg_server.py`: *needs Pillow* | `.venv/bin/python -m ensurepip --upgrade && .venv/bin/python -m pip install Pillow` (only the MJPEG mode uses it) |
| No audio in Zoom | wrong microphone: pick `USB Camera-B4.09.24.1` |
| Double audio / echo | both `Mic/Aux` (system mic) and the PS Eye are active: pick one |
| Stuttering video | lower `--quality`, or switch to `--res qvga` / `--fps 30` |
| Two PS Eyes: the second will not open, or one stutters | USB 2.0 bandwidth saturated: see [`docs/mjpeg.md`](docs/mjpeg.md#two-ps-eyes-at-once) |
| `--index 1` → *No camera available at index 1* | index does not exist: start without `--index` and read `Connected PS3 Eye cameras: N` |
| Microphone permission denied | *System Settings → Privacy & Security → Microphone* → enable Zoom/OBS |

## Verifying it works

`./pseye doctor` checks the whole chain and is the first thing to run. To look
at the actual frames, or at the microphone, see
[`docs/verifying.md`](docs/verifying.md).

## Tests

```bash
./tests/run.sh          # everything, including the camera
./tests/run.sh cli      # only the tests that need no camera
```

No dependencies beyond bash and the virtualenv. The tests run against stubs
(`tests/bin/ioreg`, `tests/bin/launchctl`) in a throwaway state directory, so
the real `~/Library/Application Support/pseye` is never touched. They cover the
CLI, `doctor`, `autostart`, `uninstall` and the supervisor lifecycle (child
exits on its own, stale heartbeat, unplug, `SIGTERM`, the LED fallback). The
camera tests are skipped when the PS Eye is not plugged in, and the whole run
takes about a minute.

GitHub Actions runs `./tests/run.sh cli` on every push to `main` and on every
pull request (`.github/workflows/tests.yml`). The runner has no camera, so the
hardware tests skip themselves there; everything else runs.

Several checks exist because of bugs that already happened once: `doctor`
stopping at `in use` when the camera is unplugged, `pseye on` reporting `ON`
for a process that never delivered a frame, `on --fps 30` being ignored on a
running webcam, the supervisor adopting a stuck `vcam.py` instead of replacing
it, and `autostart remove` leaving `.args` or `launchd.log` behind.

## Files

| File | Purpose |
|---|---|
| `pseye` | Control command: `on` / `off` / `toggle` / `status` / `doctor` / `setup` / `uninstall` / `set` / `autostart` |
| `vcam.py` | PS Eye → system webcam via pyvirtualcam |
| `vcam.sh` | Convenience launcher for `vcam.py`, with the in-use guard |
| `led_off.py` | Turns the LED off when `vcam.py` had to be killed and could not do it itself |
| `mjpeg_server.py` | MJPEG server for an OBS Browser Source; `--index N` selects the camera |
| `start.sh` | Convenience launcher for the MJPEG server |
| `requirements.txt` | Pinned Python dependencies (pseyepy from fork, pyvirtualcam, NumPy); Pillow only for the MJPEG server |
| `patches/` | Fixes for the PS3EYEDriver teardown crash (upstream and pseyepy) |
| `tests/` | Test suite: `./tests/run.sh`, with stubs for `ioreg` and `launchctl` |
| `docs/` | Reference material: how it works, verifying by hand, the MJPEG mode |
| `~/Library/Application Support/pseye/` | Runtime state, not code: `vcam.log`, `launchd.log`, `.settings`, `.heartbeat`, `.paused`, `.args` (override with `PSEYE_STATE_DIR`) |

## License

GPL-2.0 — see [`LICENSE`](LICENSE). This project imports pyvirtualcam, which is
GPL-2.0, so it is a derivative work. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the licenses of everything
it builds on, including the MIT/GPL-2.0 split of PS3EYEDriver.

### Legal notes

This project does not redistribute OBS Studio or its Camera Extension, and the
PS Eye protocol was reverse engineered by others. The details are in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md#legal-notes).

## Credits

- [inspirit/PS3EYEDriver](https://github.com/inspirit/PS3EYEDriver) — the C driver
- [bensondaled/pseyepy](https://github.com/bensondaled/pseyepy) — the Python wrapper
- [letmaik/pyvirtualcam](https://github.com/letmaik/pyvirtualcam) — the virtual camera bridge
- [libusb](https://github.com/libusb/libusb) — USB access
- [OBS Studio](https://obsproject.com/) — the signed Camera Extension
