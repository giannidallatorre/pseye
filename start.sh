#!/bin/bash
# Start the PS3 Eye MJPEG server for an OBS Browser Source.
# Usage:  ./start.sh [--port 8090] [--fps 30] [--res vga|qvga] [--quality 80] [--index N]
# With two PS Eyes, run it twice on different ports and different --index:
#   ./start.sh --index 0 --port 8090
#   ./start.sh --index 1 --port 8091
set -euo pipefail

# Resolve symlinks so this script also works when linked from ~/.local/bin.
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
PY="${PSEYE_PYTHON:-$DIR/.venv/bin/python}"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: Python environment not found at $PY" >&2
  echo "       Set up the virtualenv first:" >&2
  echo "         python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

PORT=8090
for ((i = 1; i <= $#; i++)); do
  if [[ "${!i}" == "--port" ]]; then
    j=$((i + 1))
    PORT="${!j}"
  fi
done

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT already in use: the server looks like it is already running."
  echo "Open http://localhost:$PORT in OBS (Browser Source)."
  exit 0
fi

echo "Starting PS3 Eye MJPEG on http://localhost:$PORT ..."
echo "In OBS: + -> Browser -> URL http://localhost:$PORT"
echo "Then: Start Virtual Camera -> in Zoom pick 'OBS Virtual Camera'."
echo "Ctrl-C to quit."
echo
exec "$PY" "$DIR/mjpeg_server.py" "$@"
