#!/usr/bin/env python3
"""PS Eye -> system webcam, without OBS running.

Reads frames from the PS Eye through pseyepy (libusb) and pushes them to the
OBS Camera Extension via pyvirtualcam. OBS must be installed and its virtual
camera activated once (see README), but OBS itself must NOT be running:
this script feeds the webcam on its own.

Performance notes
-----------------
* The PS Eye does 640x480 @ 60 fps (and up to 125 fps at 320x240). The default
  here is 60 fps; use --fps 30 if the USB bus is congested or you want less CPU.
  The driver rounds the requested fps down to the nearest rate it supports.
* The PS3EYEDriver defaults are all-manual (gain=20, exposure=128, AWB off),
  which gives a dark, red-tinted image. Auto gain + auto white balance are
  enabled by default here because they look much better.
* --gray skips the Bayer->RGB conversion and sends 1/3 of the data; useful
  for tracking (head tracking, motion detection) where colour is irrelevant.
"""
import argparse
import os
import signal
import sys
import time

import numpy as np
import pyvirtualcam
from pseyepy import Camera, cam_count

# Runtime state lives outside the checkout (see `pseye`): it is not code, and a
# packaged install has no writable checkout to put it in.
STATE_DIR = os.environ.get(
    "PSEYE_STATE_DIR",
    os.path.join(os.path.expanduser("~"), "Library", "Application Support", "pseye"),
)

# Written every couple of seconds while frames are flowing. `pseye status` and
# `pseye on` use its mtime to distinguish "process alive" from "camera actually
# working": a stuck cam.read() leaves the process alive but the heartbeat stale.
HEARTBEAT = os.environ.get("PSEYE_HEARTBEAT", os.path.join(STATE_DIR, ".heartbeat"))
HEARTBEAT_INTERVAL = 2.0


def write_heartbeat(fps: float | None = None) -> None:
    # The mtime is what `pseye` checks; the fps is a bonus for `pseye status`,
    # measured over the last interval so it reflects what is really flowing.
    try:
        with open(HEARTBEAT, "w") as fh:
            fh.write(f"{time.time():.0f}" + (f" {fps:.1f}" if fps else ""))
    except OSError:
        pass


# Live-adjustable image controls. `pseye set` writes this file and sends
# SIGHUP; vcam.py re-reads it between frames, so no restart is needed.
SETTINGS = os.environ.get("PSEYE_SETTINGS", os.path.join(STATE_DIR, ".settings"))

# .settings key -> Camera attribute. The keys match the vcam.py flags.
LIVE_PARAMS = {
    "auto-gain": "auto_gain",
    "gain": "gain",
    "auto-exposure": "auto_exposure",
    "exposure": "exposure",
    "auto-wb": "auto_whitebalance",
    "red": "red_balance",
    "green": "green_balance",
    "blue": "blue_balance",
    "flip-h": "hflip",
    "flip-v": "vflip",
}
BOOL_PARAMS = {"auto-gain", "auto-exposure", "auto-wb", "flip-h", "flip-v"}
# Auto flags first, then the values they gate.
PARAM_ORDER = ["auto-gain", "auto-exposure", "auto-wb",
               "gain", "exposure", "red", "green", "blue",
               "flip-h", "flip-v"]
DEFAULTS = {"auto-gain": "on", "auto-exposure": "off", "auto-wb": "on",
            "flip-h": "off", "flip-v": "off"}


def read_settings() -> dict:
    values = {}
    try:
        with open(SETTINGS) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def write_settings(values: dict) -> None:
    try:
        with open(SETTINGS, "w") as fh:
            for key in PARAM_ORDER:
                if key in values:
                    fh.write(f"{key}={values[key]}\n")
    except OSError:
        pass


def read_baseline(cam: Camera) -> dict:
    """The driver's own defaults, read before we touch anything."""
    return {key: int(getattr(cam, LIVE_PARAMS[key])[0])
            for key in ("gain", "exposure", "red", "green", "blue")}


def apply_settings(cam: Camera, values: dict, baseline: dict) -> None:
    # A manual value is meaningless while its auto flag is on: the driver would
    # either ignore it or silently switch the auto mode off.
    auto_gain = values.get("auto-gain", DEFAULTS["auto-gain"]) == "on"
    auto_exposure = values.get("auto-exposure", DEFAULTS["auto-exposure"]) == "on"
    auto_wb = values.get("auto-wb", DEFAULTS["auto-wb"]) == "on"

    # Turning an auto mode back on does not clear the manual registers in the
    # driver, so the image would keep the last manual look. Restore the
    # baseline values first, while the auto mode is still off.
    if auto_gain:
        cam.gain = baseline["gain"]
    if auto_exposure:
        cam.exposure = baseline["exposure"]
    if auto_wb:
        cam.auto_whitebalance = False
        for key in ("red", "green", "blue"):
            setattr(cam, LIVE_PARAMS[key], baseline[key])

    for key in PARAM_ORDER:
        if key not in values:
            continue
        if key == "gain" and auto_gain:
            continue
        if key == "exposure" and auto_exposure:
            continue
        if key in ("red", "green", "blue") and auto_wb:
            continue
        raw = values[key]
        if key in BOOL_PARAMS:
            value = raw.lower() in ("1", "on", "true", "yes")
        else:
            value = int(raw)
        setattr(cam, LIVE_PARAMS[key], value)


def cli_overrides(args: argparse.Namespace) -> dict:
    """Only the controls explicitly requested on the command line."""
    values = {}
    if args.no_auto_gain:
        values["auto-gain"] = "off"
    if args.gain is not None:
        values["gain"] = str(args.gain)
        values["auto-gain"] = "off"
    if args.auto_exposure:
        values["auto-exposure"] = "on"
    if args.exposure is not None:
        values["exposure"] = str(args.exposure)
        values["auto-exposure"] = "off"
    if args.no_auto_wb:
        values["auto-wb"] = "off"
    for key, value in (("red", args.red), ("green", args.green), ("blue", args.blue)):
        if value is not None:
            values[key] = str(value)
            values["auto-wb"] = "off"
    if args.flip_h:
        values["flip-h"] = "on"
    if args.flip_v:
        values["flip-v"] = "on"
    return values


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="PS Eye -> system webcam (pyvirtualcam / OBS Camera Extension)"
    )
    p.add_argument("--camera", type=int, default=0, help="PS Eye index (default: 0)")
    p.add_argument("--width", type=int, default=640, help="capture width (default: 640)")
    p.add_argument("--height", type=int, default=480, help="capture height (default: 480)")
    p.add_argument("--fps", type=int, default=60,
                   help="capture fps: 15/30/40/50/60 at 640x480, up to 125 at 320x240 (default: 60)")
    p.add_argument("--gray", action="store_true",
                   help="grayscale output (1/3 of the data, no colour conversion)")
    p.add_argument("--stats", type=float, default=0.0,
                   help="seconds between fps log lines, 0 to disable (default: 0)")

    img = p.add_argument_group("image controls")
    img.add_argument("--no-auto-gain", action="store_true", help="disable auto gain")
    img.add_argument("--gain", type=int, metavar="0-63", help="manual gain")
    img.add_argument("--auto-exposure", action="store_true",
                     help="enable auto exposure (unstable in this driver, off by default)")
    img.add_argument("--exposure", type=int, metavar="0-255", help="manual exposure")
    img.add_argument("--no-auto-wb", action="store_true", help="disable auto white balance")
    img.add_argument("--red", type=int, metavar="0-255", help="manual red balance")
    img.add_argument("--green", type=int, metavar="0-255", help="manual green balance")
    img.add_argument("--blue", type=int, metavar="0-255", help="manual blue balance")
    img.add_argument("--flip-h", action="store_true", help="mirror horizontally")
    img.add_argument("--flip-v", action="store_true", help="flip vertically")
    return p


def main() -> int:
    args = build_parser().parse_args()

    # `pseye` creates this too, but vcam.py can also be run on its own.
    os.makedirs(STATE_DIR, exist_ok=True)

    # Behave like a normal CLI tool when the reader of our stderr goes away.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    # Shut down cleanly on `pkill` / `pseye off` (SIGTERM) as well as Ctrl-C.
    def _on_term(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_term)

    # `pseye set` rewrites .settings and sends SIGHUP; the loop below applies it.
    reload_settings = False

    def _on_hup(_signum, _frame):
        nonlocal reload_settings
        reload_settings = True

    signal.signal(signal.SIGHUP, _on_hup)

    found = cam_count()
    if found == 0:
        print("[vcam] no PS Eye found on the USB bus", file=sys.stderr, flush=True)
        return 1
    if args.camera >= found:
        print(f"[vcam] camera index {args.camera} out of range ({found} found)",
              file=sys.stderr, flush=True)
        return 1

    resolution = Camera.RES_LARGE if args.width >= 640 else Camera.RES_SMALL
    colour = not args.gray
    cam = Camera(ids=[args.camera], resolution=resolution, fps=args.fps, colour=colour)
    baseline = read_baseline(cam)
    # Saved settings first, then the flags given on this command line. They are
    # applied after the first frame: enabling AWB/AGC before the sensor has
    # produced one leaves them in a state where they never converge.
    settings = {**DEFAULTS, **read_settings()}
    settings.update(cli_overrides(args))
    pending = True

    frames = 0
    frames_hb = 0
    t0 = time.time()
    t_last = t0
    t_heartbeat = 0.0
    try:
        fmt = pyvirtualcam.PixelFormat.GRAY if args.gray else pyvirtualcam.PixelFormat.RGB
        with pyvirtualcam.Camera(width=args.width, height=args.height,
                                 fps=args.fps, fmt=fmt) as vcam:
            mode = "gray" if args.gray else "rgb"
            print(f"[vcam] system webcam: {vcam.device}", file=sys.stderr, flush=True)
            print(f"[vcam] PS Eye {args.width}x{args.height} @ {args.fps}fps {mode}"
                  f" -> {vcam.device}", file=sys.stderr, flush=True)
            write_heartbeat()
            t_heartbeat = time.time()
            while True:
                frame, _ts = cam.read()
                if frame is None:
                    continue
                if pending:
                    apply_settings(cam, settings, baseline)
                    write_settings(settings)
                    pending = False
                if reload_settings:
                    reload_settings = False
                    try:
                        values = {**DEFAULTS, **read_settings()}
                        apply_settings(cam, values, baseline)
                        write_settings(values)
                        print("[vcam] settings reloaded", file=sys.stderr, flush=True)
                    except (OSError, ValueError) as exc:
                        print(f"[vcam] settings reload failed: {exc}",
                              file=sys.stderr, flush=True)
                # pseyepy already hands us a contiguous array; this is a no-op
                # guard for the odd case where it does not.
                if not frame.flags["C_CONTIGUOUS"]:
                    frame = np.ascontiguousarray(frame)
                vcam.send(frame)
                vcam.sleep_until_next_frame()
                frames += 1
                frames_hb += 1
                now = time.time()
                if now - t_heartbeat >= HEARTBEAT_INTERVAL:
                    write_heartbeat(frames_hb / (now - t_heartbeat))
                    frames_hb = 0
                    t_heartbeat = now
                if args.stats:
                    if now - t_last >= args.stats:
                        dt = now - t_last
                        print(f"[vcam] {frames} frames in {dt:.1f}s ({frames / dt:.1f} fps)",
                              file=sys.stderr, flush=True)
                        frames = 0
                        t_last = now
    except KeyboardInterrupt:
        pass
    finally:
        print(f"[vcam] closed after {time.time() - t0:.1f}s", file=sys.stderr, flush=True)
        # cam.end() stops the transfers and turns the LED off (PS3EYECam::stop()
        # clears the LED register). This used to abort the process: the driver
        # called libusb_cancel_transfer() on transfers it had already freed,
        # which tripped a libusb assertion (5 crashes out of 8 shutdowns). The
        # fix is in the pseyepy fork (23624c2), so the teardown is safe now.
        try:
            cam.end()
        except Exception as exc:  # noqa: BLE001
            print(f"[vcam] cam.end() failed: {exc}", file=sys.stderr, flush=True)
        # Still exit hard: it guarantees we never hang in interpreter shutdown
        # (pseyepy's atexit handler would call end() again, which is a no-op).
        os._exit(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
