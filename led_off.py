#!/usr/bin/env python3
"""Turn the PS Eye's LED off.

Why this exists
---------------
The LED is driven by the camera's own registers: PS3EYEDriver sets it on in
PS3EYECam::start() (ov534_set_led(1)) and off in PS3EYECam::stop()
(ov534_set_led(0)). stop() is only reached through Camera.end().

vcam.py cannot call Camera.end() itself: the driver's teardown races with its
own transfer thread and aborts the process (SIGABRT, "Abort trap: 6") in about
60% of shutdowns while pyvirtualcam is running. So vcam.py exits with
os._exit(0) and the camera is never told to stop -> the LED stays on until the
next replug.

This helper runs *after* vcam.py is gone, with no pyvirtualcam load, where the
same open/close cycle is reliable (measured 15/15 clean). Opening the camera
ends with ov534_set_led(0) and closing calls stop() -> ov534_set_led(0) again,
so the LED ends up off either way.

Usage:  python led_off.py        (silent, always exits 0)
"""
import sys

from pseyepy import Camera, cam_count


def main() -> int:
    if cam_count() == 0:
        return 0
    try:
        cam = Camera(ids=[0], resolution=Camera.RES_SMALL, fps=30, colour=False)
    except Exception:  # noqa: BLE001
        return 0
    try:
        cam.end()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
