#!/usr/bin/env python3
"""PS Eye -> system webcam, without OBS running.

Reads frames from the PS Eye through pseyepy (libusb) and pushes them to the
OBS Camera Extension via pyvirtualcam. OBS must be installed and its virtual
camera activated once (see README), but OBS itself must NOT be running:
this script feeds the webcam on its own.

Performance notes
-----------------
* The PS Eye does 640x480 @ 60 fps (and 320x240 @ 120 fps). The default here
  is 60 fps; use --fps 30 if the USB bus is congested or you want less CPU.
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
    p.add_argument("--stats", type=float, default=5.0,
                   help="seconds between fps log lines, 0 to disable (default: 5)")

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


def apply_controls(cam: Camera, args: argparse.Namespace) -> None:
    """Push the requested image controls onto the camera."""
    if not args.no_auto_gain:
        cam.auto_gain = True
    if args.gain is not None:
        cam.auto_gain = False
        cam.gain = args.gain
    if args.auto_exposure:
        cam.auto_exposure = True
    if args.exposure is not None:
        cam.auto_exposure = False
        cam.exposure = args.exposure
    if not args.no_auto_wb:
        cam.auto_whitebalance = True
    for name, value in (("red_balance", args.red),
                        ("green_balance", args.green),
                        ("blue_balance", args.blue)):
        if value is not None:
            cam.auto_whitebalance = False
            setattr(cam, name, value)
    if args.flip_h:
        cam.hflip = True
    if args.flip_v:
        cam.vflip = True


def main() -> int:
    args = build_parser().parse_args()

    # Behave like a normal CLI tool when the reader of our stderr goes away.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    # Shut down cleanly on `pkill` / `pseye off` (SIGTERM) as well as Ctrl-C.
    def _on_term(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_term)

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
    apply_controls(cam, args)

    frames = 0
    t0 = time.time()
    t_last = t0
    try:
        fmt = pyvirtualcam.PixelFormat.GRAY if args.gray else pyvirtualcam.PixelFormat.RGB
        with pyvirtualcam.Camera(width=args.width, height=args.height,
                                 fps=args.fps, fmt=fmt) as vcam:
            mode = "gray" if args.gray else "rgb"
            print(f"[vcam] system webcam: {vcam.device}", file=sys.stderr, flush=True)
            print(f"[vcam] PS Eye {args.width}x{args.height} @ {args.fps}fps {mode}"
                  f" -> {vcam.device}", file=sys.stderr, flush=True)
            while True:
                frame, _ts = cam.read()
                if frame is None:
                    continue
                # pseyepy already hands us a contiguous array; this is a no-op
                # guard for the odd case where it does not.
                if not frame.flags["C_CONTIGUOUS"]:
                    frame = np.ascontiguousarray(frame)
                vcam.send(frame)
                vcam.sleep_until_next_frame()
                frames += 1
                if args.stats:
                    now = time.time()
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
        # Do NOT call cam.end() here. PS3EYEDriver's teardown races with its
        # own transfer thread: close_transfers() calls libusb_cancel_transfer()
        # while the transfer thread is inside libusb_handle_events_timeout(),
        # which trips a libusb assertion and aborts the process (SIGABRT,
        # "Abort trap: 6"). Measured with pyvirtualcam running: 5 crashes out
        # of 8 shutdowns. Without pyvirtualcam the same teardown is clean
        # (15/15), which is why the LED is turned off by led_off.py instead,
        # run by `pseye off` *after* this process is gone.
        # os._exit(0) also skips pseyepy's atexit handler, which calls end().
        os._exit(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
