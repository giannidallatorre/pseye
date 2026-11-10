# How it works, and what it does not do

Reference material moved out of the README: the pipeline, the parts of the
system that are easy to get wrong, and the limitations worth knowing before
blaming the wrong component.

## The pipeline

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

## The LED

The LED is driven by the camera's own registers (`PS3EYECam::start()` sets it,
`PS3EYECam::stop()` clears it), and `stop()` is only reached through
`Camera.end()`. `vcam.py` calls `cam.end()` on the way out, so `./pseye off`
turns the LED off and releases the USB interface.

When the process has to be killed with `SIGKILL` — the camera stopped answering,
so `cam.read()` is blocked in C++ and the `SIGTERM` handler never runs — that
cleanup is skipped, and `pseye off` falls back to `led_off.py` in a separate
process, with a timeout. If the camera has already dropped off the bus, nothing
can reach it: only unplugging it turns the LED off.

## Why `Camera.end()` used to abort the process

PS3EYEDriver's teardown called `libusb_cancel_transfer()` on transfers it had
already freed, which tripped a libusb assertion (`Abort trap: 6`): 5 crashes out
of 8 shutdowns with pyvirtualcam running. The fix is in the pseyepy fork this
project pins (`23624c2`, also in [`patches/`](../patches/)); with it, 10 out of
10 on/off cycles are clean. `vcam.py` still exits with `os._exit(0)` so that
shutdown can never hang.

## Things that look like bugs and are not

- **`vcam.sh` refuses to start** if another process already holds the camera's
  video interface (it checks `UsbExclusiveOwner` on `IOUSBHostInterface@0` via
  `ioreg`). This avoids the segfault pseyepy hits when the device is already
  open.
- **`libusb: darwin_reenumerate_device ... not opened for exclusive access`** on
  close is a harmless known warning from libusb's macOS backend.
- **Zoom caches the camera list** at launch: restart Zoom after changing which
  cameras are available.
- The PS Eye has a **single sensor**; it is not a stereo camera. `cam_count()`
  returns 1 per device. True stereo needs two cameras plus calibration.

## When the camera stops answering

The PS Eye can wedge: the kernel log shows `status 0xe00002ed (transaction
error)` on endpoint 0x81, which is `kIOReturnNotResponding`, and `pseye status`
says `ON (no frames)` while the USB link is still 480 Mbps. Reopening the device
is not enough — only unplugging and plugging it back in brings it back. A
different port or cable is worth trying: the same camera that wedged on one port
has run for an hour on another.
