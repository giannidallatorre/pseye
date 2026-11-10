# Alternative mode: MJPEG server

Instead of feeding the virtual camera directly, the frames can be served over
HTTP as MJPEG and consumed by an OBS Browser Source. This is useful when you
want OBS to do the compositing, or when you want the stream in a browser.

```bash
./start.sh                      # http://localhost:8090, 30 fps, VGA
./start.sh --res qvga --fps 60  # 320x240 @ 60 fps
./start.sh --quality 90         # sharper JPEG
./start.sh --port 8091          # different port
```

In OBS: `+` → **Browser** → URL `http://localhost:8090`, then
`Start Virtual Camera`. Stop the server with Ctrl-C or
`pkill -f mjpeg_server.py`.

This mode is the only one that needs **Pillow**, which is therefore not in
`requirements.txt` (the virtual camera path does not use it):

```bash
.venv/bin/python -m ensurepip --upgrade   # setup trims pip from the venv
.venv/bin/python -m pip install Pillow
```

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
