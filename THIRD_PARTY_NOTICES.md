# Third-party notices

This project is a thin integration layer. Almost all of the hard work is done by
other people's code; this file records what is used and under which terms.

## Runtime dependencies (imported by this project)

| Component | Version used | License | Role |
|---|---|---|---|
| [pyvirtualcam](https://github.com/letmaik/pyvirtualcam) | 0.15.0 | **GPL-2.0** | Feeds frames to the OBS Camera Extension (`obs_cmioextension` backend) |
| [pseyepy](https://github.com/giannidallatorre/pseyepy) | fork `c0f8372` | Apache-2.0 | Python wrapper around PS3EYEDriver (with teardown fix and clean build) |
| [PS3EYEDriver](https://github.com/inspirit/PS3EYEDriver) | vendored in pseyepy | MIT **and** GPL-2.0 | The actual C driver (see below) |
| [libusb](https://github.com/libusb/libusb) | 1.0.30 | LGPL-2.1 | USB access, linked by PS3EYEDriver |
| [Pillow](https://python-pillow.org/) | 12.3.0 | MIT-CMU (HPND) | JPEG encoding in `mjpeg_server.py` |
| [NumPy](https://numpy.org/) | 2.5.3 | BSD-3-Clause | Frame buffers |

### Why this project is GPL-2.0

`vcam.py` imports **pyvirtualcam**, which is licensed GPL-2.0. Importing it makes
this program a derivative work of a GPL-2.0 library, so this project is released
under **GPL-2.0** as well. See `LICENSE`.

`mjpeg_server.py` does not use pyvirtualcam (it only needs pseyepy + Pillow), but
it is distributed in the same repository and under the same license for
simplicity.

### PS3EYEDriver: MIT *and* GPL-2.0

PS3EYEDriver is a mixed-license work. From its own `LICENSE` file:

> The license of the PS3EYEDriver is MIT (for newly-written code) and GPLv2 for
> all code derived from the Linux Kernel Driver (ov534) sources.

The `ov534` register tables and the LED/streaming logic come from the Linux
kernel's `drivers/media/usb/gspca/ov534.c`:

```
Copyright (C) 2008 Antonio Ospite <ospite@studenti.unina.it>
Copyright (C) 2008 Jim Paris <jim@jtan.com>
Copyright (C) 2009 Jean-Francois Moine http://moinejf.free.fr
```

That is why the LED is controlled by writing bit 7 of registers `0x21` and
`0x23` — see `PS3EYECam::ov534_set_led()`.

## External software (not redistributed)

| Component | License | Role |
|---|---|---|
| [OBS Studio](https://obsproject.com/) | GPL-2.0 | Provides the signed **OBS Virtual Camera** Camera Extension that `pyvirtualcam` drives. Must be installed and its virtual camera activated once; OBS itself does not need to run. |

## Prior art and references

- [opentrack](https://github.com/opentrack/opentrack) — includes a PS3 Eye
  driver; the reference for head tracking with this camera.
- [teknoman117/StereoPS3Eye](https://github.com/teknoman117/StereoPS3Eye),
  [pio127/stereo-camera-opencv](https://github.com/pio127/stereo-camera-opencv) —
  true stereo with two PS Eyes.
