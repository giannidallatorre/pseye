# Verifying it works

Moved out of the README: the commands to check each part of the chain by hand,
without trusting the preview in Zoom.

## The virtual camera

```bash
# grab a frame from the system webcam and check it is not black
IDX=$(ffmpeg -f avfoundation -list_devices true -i "" 2>&1 | grep "OBS Virtual Camera" | sed -E 's/.*\[([0-9]+)\].*/\1/')
ffmpeg -y -f avfoundation -pix_fmt uyvy422 -framerate 60 -video_size 1920x1080 -i "${IDX}:none" -frames:v 1 -f rawvideo -pix_fmt rgb24 /tmp/cap.raw
.venv/bin/python -c "import numpy as np; a=np.fromfile('/tmp/cap.raw',dtype=np.uint8).reshape(1080,1920,3); print('mean', a.reshape(-1,3).mean(0).round(1), 'std', a.reshape(-1,3).std(0).round(1))"
```

`-pix_fmt uyvy422` on the input is required: avfoundation rejects the `yuv420p`
ffmpeg picks by default. The extension advertises 1920x1080 but forwards the
buffer it is given, so a 640x480 stream arrives as 640x480.

## The camera itself, without the virtual camera

```bash
.venv/bin/python -c "
from pseyepy import Camera
c = Camera(ids=[0], resolution=Camera.RES_LARGE, fps=60, colour=True)
for _ in range(30): f,_ = c.read()
c.end()
print('frame', f.shape, 'mean R G B', f.reshape(-1,3).mean(0).round(1))
"
```

Point it at something white and the three channel means should be close; point
it at something red and R should dominate. That is the quickest way to tell a
white-balance problem from a channel swap.

## The MJPEG server

```bash
curl -s --max-time 3 http://localhost:8090/stream -o /tmp/t.bin && \
  python3 -c "d=open('/tmp/t.bin','rb').read(); print('frames:', d.count(b'\xff\xd8\xff'))"
```

## The microphone

```bash
AUDIO=$(ffmpeg -f avfoundation -list_devices true -i "" 2>&1 | grep "USB Camera-B4.09.24.1" | sed -E 's/.*\[([0-9]+)\].*/\1/')
ffmpeg -f avfoundation -i ":${AUDIO}" -t 3 -ac 1 -ar 16000 -y /tmp/a.wav && \
  ffmpeg -i /tmp/a.wav -af volumedetect -f null - 2>&1 | grep volume
```
