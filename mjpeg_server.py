#!/usr/bin/env python3
"""PS3 Eye -> MJPEG server, meant for an OBS Browser Source.

Usage:
    ./start.sh [--port 8090] [--fps 30] [--res vga|qvga] [--quality 80] [--index N]
    # or, with the virtualenv active:
    python mjpeg_server.py [--port 8090] [--fps 30] [--res vga|qvga] [--quality 80] [--index N]

Then in OBS:  +  ->  Browser  ->  URL: http://localhost:8090
Finally in OBS: "Start Virtual Camera"  ->  in Zoom pick "OBS Virtual Camera".

Multiple cameras: run one server per camera on a different port, e.g.
    ./start.sh --index 0 --port 8090
    ./start.sh --index 1 --port 8091
then add two Browser Sources in OBS (http://localhost:8090 and :8091).
"""
import argparse
import io
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image
from pseyepy import Camera, cam_count

BOUNDARY = "ps3eye"


class Capture:
    """Reads frames from the PS Eye in a thread and keeps the latest JPEG ready."""

    def __init__(self, fps, res, quality, index=None):
        self.res = Camera.RES_LARGE if res == "vga" else Camera.RES_SMALL
        # index=None -> all connected cameras (legacy behaviour); index=N -> only
        # camera N. With a single id, read() returns one frame (not a list), so
        # the rest of this class is unchanged.
        ids = None if index is None else [index]
        self.cam = Camera(ids=ids, fps=fps, resolution=self.res, colour=True)
        self.quality = quality
        self.latest = None
        self.seq = 0
        self.lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while self.running:
            try:
                frame, _ts = self.cam.read()
            except Exception as exc:  # noqa: BLE001
                print("read error:", exc, file=sys.stderr)
                time.sleep(0.1)
                continue
            buf = io.BytesIO()
            Image.fromarray(frame).save(buf, format="JPEG", quality=self.quality)
            with self.lock:
                self.latest = buf.getvalue()
                self.seq += 1

    def get(self):
        with self.lock:
            return self.seq, self.latest

    def close(self):
        self.running = False
        try:
            self.cam.end()
        except Exception:  # noqa: BLE001
            pass


class Handler(BaseHTTPRequestHandler):
    capture = None
    # Send each frame as a single write, no Nagle buffering: this is what
    # keeps the stream at a steady 30 fps instead of stuttering.
    disable_nagle_algorithm = True

    def log_message(self, *args):  # silence the per-frame log
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (
                b"<!doctype html><html><head><meta charset='utf-8'>"
                b"<title>PS3 Eye</title></head>"
                b"<body style='margin:0;background:#000'>"
                b"<img src='/stream' style='width:100%;height:auto'>"
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if self.path == "/stream":
            self.send_response(200)
            self.send_header(
                "Content-Type",
                f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            )
            self.end_headers()
            last = -1
            try:
                while True:
                    seq, jpg = self.capture.get()
                    # Skip frames we have already sent: the client sets the
                    # pace, and we never push the same JPEG twice.
                    if jpg is None or seq == last:
                        time.sleep(0.005)
                        continue
                    last = seq
                    chunk = (
                        b"--" + BOUNDARY.encode() + b"\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n"
                        + jpg
                        + b"\r\n"
                    )
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        self.send_error(404)


def main():
    ap = argparse.ArgumentParser(description="PS3 Eye MJPEG server")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--res", choices=["vga", "qvga"], default="vga")
    ap.add_argument("--quality", type=int, default=80)
    ap.add_argument(
        "--index",
        type=int,
        default=None,
        help="camera index to use (0, 1, ...). Default: all connected cameras.",
    )
    args = ap.parse_args()

    if args.index is None:
        print(f"Connected PS3 Eye cameras: {cam_count()}")
    try:
        cap = Capture(args.fps, args.res, args.quality, args.index)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not open the camera: {exc}", file=sys.stderr)
        return 1
    Handler.capture = cap
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"PS3 Eye MJPEG on http://localhost:{args.port}  (Ctrl-C to quit)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
        cap.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
