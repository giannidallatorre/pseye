#!/usr/bin/env python3
"""Turn the PS Eye's LED off, after vcam.py could not.

Why this exists
---------------
The LED is driven by the camera's own registers: PS3EYEDriver sets it on in
PS3EYECam::start() (ov534_set_led(1)) and off in PS3EYECam::stop()
(ov534_set_led(0)). stop() is only reached through Camera.end(), which vcam.py
calls in its finally block.

That finally block does not run when the process has to be killed with SIGKILL,
which is exactly what happens when the camera stops answering: cam.read() is
blocked in C++, Python never regains control, and the SIGTERM handler never
runs. The LED then stays on until the camera is unplugged.

This helper runs after vcam.py is gone, with no pyvirtualcam loaded, where the
same open/close cycle is reliable. Opening the camera ends with
ov534_set_led(0) and closing calls stop() -> ov534_set_led(0) again, so the LED
ends up off either way. If the camera is wedged it may fail or hang, which is
why `pseye` runs it with a timeout.

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
