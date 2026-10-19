#!/bin/bash
# PS Eye -> system webcam, without OBS running.
#
# Requires: OBS installed with its virtual camera activated once (see README).
# OBS itself must NOT stay open.
#
# Usage:  ./vcam.sh [--fps 60] [--gray] [--stats 5] ...
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PSEYE_PYTHON:-$DIR/.venv/bin/python}"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: Python environment not found at $PY" >&2
  echo "       Set up the virtualenv first:" >&2
  echo "         python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi


# Guard: the PS Eye must not already be claimed by another process, otherwise
# pseyepy segfaults on open. Interface 0 is the video interface; the audio
# interface is a different one, so we only look at IOUSBHostInterface@0.
OWNER="$(ioreg -w0 -l -r -n "USB Camera-B4.09.24.1" 2>/dev/null | awk '
  /IOUSBHostInterface@/ { in0 = ($0 ~ /IOUSBHostInterface@0 /) }
  in0 && /"UsbExclusiveOwner"/ { l=$0; sub(/.*= "/,"",l); sub(/".*/,"",l); print l; exit }
')"
if [[ -n "$OWNER" ]]; then
  echo "ERROR: the PS Eye is already in use by: $OWNER" >&2
  echo "       Stop that process (e.g. pkill -f mjpeg_server.py) and retry." >&2
  exit 1
fi

exec "$PY" "$DIR/vcam.py" "$@"
