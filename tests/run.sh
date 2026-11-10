#!/bin/bash
# Test suite for pseye.
#
#   ./tests/run.sh            everything
#   ./tests/run.sh cli        only the tests that need no camera
#
# No dependencies beyond bash and the project's virtualenv. The camera tests
# are skipped when the PS Eye is not plugged in; everything else runs against
# stubs (tests/bin/ioreg, tests/bin/launchctl) in a throwaway state directory,
# so the real ~/Library/Application Support/pseye is never touched.
#
# Note: the tests that exercise `off` and `uninstall` stop any running webcam,
# because that is what those commands do. They are skipped if one is running.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TESTS="$ROOT/tests"
REAL_PATH="$PATH"
TMP="$(mktemp -d)"
# KEEP=1 leaves the sandboxes behind for debugging.
trap '[[ -n "${KEEP:-}" ]] || rm -rf "$TMP"' EXIT

pass=0 fail=0 skipped=0
ok()   { pass=$((pass + 1)); printf '  ok    %s\n' "$1"; }
bad()  { fail=$((fail + 1)); printf '  FAIL  %s\n' "$1"; [[ $# -gt 1 ]] && printf '        %s\n' "$2"; }
skip() { skipped=$((skipped + 1)); printf '  skip  %s\n' "$1"; }
group() { printf '\n%s\n' "$1"; }

# A sandbox holds a copy of the script, a fake vcam.py and a private state
# directory, so nothing leaks into the checkout or the real state.
sandbox() {
  SB="$TMP/$1"
  APP="$SB/app"
  mkdir -p "$APP" "$SB/home/Library/LaunchAgents"
  cp "$ROOT/pseye" "$APP/pseye"
  chmod +x "$APP/pseye"
  cat > "$APP/vcam.sh" <<'EOF'
#!/bin/bash
exec bash "$(dirname "$0")/vcam.py" "$@"
EOF
  cat > "$APP/vcam.py" <<'EOF'
#!/bin/bash
# Stand-in for vcam.py: writes the heartbeat, then behaves per FAKE_MODE.
hb="${PSEYE_STATE_DIR}/.heartbeat"
case "${FAKE_MODE:-stream}" in
  exit)     exit 0 ;;
  stale)    date +%s > "$hb"; sleep 600 ;;
  stubborn) trap '' TERM; while :; do date +%s > "$hb"; sleep 2; done ;;
  *)        while :; do date +%s > "$hb"; sleep 2; done ;;
esac
EOF
  chmod +x "$APP/vcam.sh" "$APP/vcam.py"
  export PSEYE_STATE_DIR="$SB/state"
  export HOME="$SB/home"
  export PSEYE_TEST_LAUNCHD="$SB/launchd.loaded"
  export PSEYE_TEST_USB=absent
  export PATH="$TESTS/bin:$REAL_PATH"
  unset PSEYE_PYTHON PSEYE_TEST_PYCALLS FAKE_MODE PSEYE_TEST_USB_FILE
}

# Back to the real machine, for the tests that need the actual camera.
realenv() {
  export PATH="$REAL_PATH"
  unset PSEYE_TEST_USB PSEYE_TEST_LAUNCHD PSEYE_TEST_USB_FILE
  unset PSEYE_PYTHON PSEYE_TEST_PYCALLS FAKE_MODE
  export PSEYE_STATE_DIR="$TMP/real-state"
  export HOME="$TMP/real-home"
  mkdir -p "$HOME"
}

camera_present() {
  ioreg -w0 -l -r -n "USB Camera-B4.09.24.1" 2>/dev/null | grep -q "IOUSBHostInterface@0"
}

webcam_running() { pgrep -f "vcam.py" >/dev/null 2>&1; }

# ---------------------------------------------------------------- static

group "static checks"

for f in pseye vcam.sh start.sh tests/run.sh tests/bin/ioreg tests/bin/launchctl; do
  if bash -n "$ROOT/$f" 2>/dev/null; then ok "bash -n $f"; else bad "bash -n $f"; fi
done

if command -v shellcheck >/dev/null 2>&1; then
  for f in pseye vcam.sh start.sh; do
    if shellcheck -S warning "$ROOT/$f" >/dev/null 2>&1; then ok "shellcheck $f"; else bad "shellcheck $f"; fi
  done
else
  skip "shellcheck (not installed)"
fi

if "$ROOT/.venv/bin/python" -m py_compile "$ROOT/vcam.py" "$ROOT/mjpeg_server.py" "$ROOT/led_off.py" 2>/dev/null; then
  ok "py_compile"
else
  bad "py_compile"
fi

# ---------------------------------------------------------------- cli

group "command line"

sandbox help
out="$("$APP/pseye" -h 2>&1)"; rc=$?
[[ $rc -eq 0 ]] && ok "-h exits 0" || bad "-h exits $rc"
grep -q "pseye autostart install" <<<"$out" && ok "-h lists autostart" || bad "-h misses autostart"

sandbox unknown
"$APP/pseye" boh >/dev/null 2>&1; rc=$?
[[ $rc -eq 1 ]] && ok "unknown command exits 1" || bad "unknown command exits $rc"

sandbox status
out="$("$APP/pseye" status 2>&1)"
grep -q "webcam:     OFF" <<<"$out" && ok "status OFF" || bad "status OFF" "$out"
[[ ! -d "$PSEYE_STATE_DIR" ]] && ok "status does not create the state dir" || bad "status created the state dir"

sandbox settings
"$APP/pseye" set >/dev/null 2>&1
"$APP/pseye" set gain 40 >/dev/null 2>&1
grep -qx "gain=40" "$PSEYE_STATE_DIR/.settings" && ok "set gain writes .settings" || bad "set gain"
grep -qx "auto-gain=off" "$PSEYE_STATE_DIR/.settings" && ok "set gain disables auto-gain" || bad "auto-gain"
"$APP/pseye" set reset >/dev/null 2>&1
grep -qx "auto-gain=on" "$PSEYE_STATE_DIR/.settings" && ok "set reset restores defaults" || bad "set reset"

# ---------------------------------------------------------------- doctor

group "doctor"

sandbox doctor_absent
out="$("$APP/pseye" doctor 2>&1)"; rc=$?
[[ $rc -eq 1 ]] && ok "doctor exits 1 with no camera" || bad "doctor exits $rc"
[[ $(grep -c ':' <<<"$out") -eq 8 ]] && ok "doctor prints all 8 checks" || bad "doctor printed $(grep -c ':' <<<"$out") lines" "$out"
grep -q "^in use:" <<<"$out" && ok "doctor reaches 'in use'" || bad "doctor stopped before 'in use'"
grep -q "^auto-start:" <<<"$out" && ok "doctor reaches 'auto-start'" || bad "doctor stopped before 'auto-start'"

sandbox doctor_present
export PSEYE_TEST_USB=present
out="$("$APP/pseye" doctor 2>&1)"
grep -q "^camera:      ok" <<<"$out" && ok "doctor sees the camera" || bad "doctor camera" "$out"
grep -q "^usb:         ok    480 Mbps" <<<"$out" && ok "doctor reports 480 Mbps" || bad "doctor usb" "$out"

sandbox doctor_degraded
export PSEYE_TEST_USB=degraded
out="$("$APP/pseye" doctor 2>&1)"
grep -q "12 Mbps" <<<"$out" && ok "doctor warns about 12 Mbps" || bad "doctor degraded" "$out"

# ---------------------------------------------------------------- on/off

group "on / off"

sandbox on_absent
out="$("$APP/pseye" on 2>&1)"; rc=$?
[[ $rc -eq 1 ]] && ok "on exits 1 with no camera" || bad "on exits $rc"
grep -q "not plugged in" <<<"$out" && ok "on says not plugged in" || bad "on message" "$out"

if webcam_running; then
  skip "off (a webcam is running)"
else
  sandbox off
  "$APP/pseye" off >/dev/null 2>&1
  [[ -f "$PSEYE_STATE_DIR/.paused" ]] && ok "off sets .paused" || bad "off did not set .paused"
  out="$("$APP/pseye" status 2>&1)"
  grep -q "paused:     yes" <<<"$out" && ok "status reports paused" || bad "status paused" "$out"
fi

# ---------------------------------------------------------------- autostart

group "autostart"

sandbox autostart
"$APP/pseye" autostart install >/dev/null 2>&1
PLIST="$HOME/Library/LaunchAgents/com.pseye.watch.plist"
[[ -f "$PLIST" ]] && ok "install writes the plist" || bad "install plist"
grep -q "<string>supervise</string>" "$PLIST" && ok "plist runs supervise" || bad "plist program"
grep -q "<key>ThrottleInterval</key><integer>1</integer>" "$PLIST" && ok "plist sets ThrottleInterval 1" || bad "plist throttle"
grep -q "<key>ExitTimeOut</key><integer>10</integer>" "$PLIST" && ok "plist sets ExitTimeOut 10" || bad "plist exittimeout"
[[ -f "$PSEYE_TEST_LAUNCHD" ]] && ok "install bootstraps the job" || bad "install bootstrap"
[[ ! -f "$PSEYE_STATE_DIR/.paused" ]] && ok "install clears .paused" || bad "install left .paused"

mkdir -p "$PSEYE_STATE_DIR"
touch "$PSEYE_STATE_DIR/.args" "$PSEYE_STATE_DIR/launchd.log" "$PSEYE_STATE_DIR/.paused"
"$APP/pseye" autostart remove >/dev/null 2>&1
[[ ! -f "$PLIST" ]] && ok "remove deletes the plist" || bad "remove plist"
[[ ! -f "$PSEYE_TEST_LAUNCHD" ]] && ok "remove boots the job out" || bad "remove bootout"
for f in .args launchd.log .paused; do
  [[ ! -f "$PSEYE_STATE_DIR/$f" ]] && ok "remove deletes $f" || bad "remove left $f"
done

# ---------------------------------------------------------------- uninstall

group "uninstall"

if webcam_running; then
  skip "uninstall (a webcam is running)"
else
  sandbox uninstall
  mkdir -p "$PSEYE_STATE_DIR"
  touch "$PSEYE_STATE_DIR/vcam.log" "$PSEYE_STATE_DIR/.settings"
  "$APP/pseye" uninstall -y >/dev/null 2>&1
  [[ ! -d "$PSEYE_STATE_DIR" ]] && ok "uninstall removes the state dir" || bad "uninstall state dir"
  [[ ! -f "$HOME/Library/LaunchAgents/com.pseye.watch.plist" ]] && ok "uninstall removes the plist" || bad "uninstall plist"
fi

# ---------------------------------------------------------------- supervise

group "supervise"

sandbox sup_exit
export PSEYE_TEST_USB=present FAKE_MODE=exit
"$APP/pseye" supervise >/dev/null 2>&1; rc=$?
[[ $rc -eq 0 ]] && ok "child exits alone -> supervisor exits 0" || bad "supervisor exit $rc"

sandbox sup_stale
export PSEYE_TEST_USB=present FAKE_MODE=stale
"$APP/pseye" supervise >/dev/null 2>&1; rc=$?
[[ $rc -eq 1 ]] && ok "stale heartbeat -> supervisor exits 1" || bad "supervisor exit $rc"

sandbox sup_unplug
export PSEYE_TEST_USB=present FAKE_MODE=stubborn
export PSEYE_TEST_USB_FILE="$SB/usb"
echo present > "$PSEYE_TEST_USB_FILE"
"$APP/pseye" supervise >/dev/null 2>&1 &
SUP=$!
sleep 2
echo absent > "$PSEYE_TEST_USB_FILE"
t0=$(date +%s)
for _ in $(seq 1 40); do
  webcam_running || break
  sleep 0.1
done
dt=$(( $(date +%s) - t0 ))
wait $SUP 2>/dev/null; rc=$?
if webcam_running; then bad "unplug did not kill the child"; else ok "unplug kills the child in ${dt}s"; fi
[[ $rc -eq 0 ]] && ok "unplug -> supervisor exits 0" || bad "supervisor exit $rc"

sandbox sup_term
export PSEYE_TEST_USB=present FAKE_MODE=stubborn
"$APP/pseye" supervise >/dev/null 2>&1 &
SUP=$!
sleep 2
kill -TERM $SUP
wait $SUP 2>/dev/null; rc=$?
[[ $rc -eq 0 ]] && ok "SIGTERM -> supervisor exits 0" || bad "supervisor exit $rc"
webcam_running && bad "SIGTERM left the child alive" || ok "SIGTERM takes the child with it"

sandbox sup_led
export PSEYE_TEST_USB=present FAKE_MODE=stubborn
cat > "$SB/pystub" <<'EOF'
#!/bin/bash
echo "$@" >> "$PSEYE_TEST_PYCALLS"
exit 0
EOF
chmod +x "$SB/pystub"
export PSEYE_PYTHON="$SB/pystub" PSEYE_TEST_PYCALLS="$SB/pycalls"
bash "$APP/vcam.py" >/dev/null 2>&1 &
sleep 1
"$APP/pseye" off >/dev/null 2>&1
grep -q "led_off.py" "$SB/pycalls" 2>/dev/null && ok "hard kill falls back to led_off.py" || bad "led_off.py not called"

# ---------------------------------------------------------------- camera

group "camera (real hardware)"

realenv
if [[ "${1:-all}" == "cli" ]]; then
  skip "camera tests (cli only)"
elif ! camera_present; then
  skip "camera tests (PS Eye not plugged in)"
else
  if webcam_running; then
    skip "camera tests (a webcam is already running)"
  else
    out="$("$ROOT/pseye" on 2>&1)"; rc=$?
    if [[ $rc -eq 0 ]]; then
      ok "on starts the webcam"
    else
      bad "on exit $rc" "$out"
      sed 's/^/        log: /' "$PSEYE_STATE_DIR/vcam.log" 2>/dev/null | tail -5
    fi
    sleep 3
    out="$("$ROOT/pseye" status 2>&1)"
    fps="$(sed -n 's/.*(\([0-9]*\) fps).*/\1/p' <<<"$out")"
    if [[ -n "$fps" && "$fps" -ge 40 ]]; then ok "status reports ${fps} fps"; else bad "status fps" "$out"; fi

    "$ROOT/pseye" off >/dev/null 2>&1
    cycles=0
    for _ in 1 2 3; do
      "$ROOT/pseye" on >/dev/null 2>&1 && cycles=$((cycles + 1))
      "$ROOT/pseye" off >/dev/null 2>&1
    done
    [[ $cycles -eq 3 ]] && ok "3 on/off cycles" || bad "$cycles/3 on/off cycles"

    "$ROOT/pseye" on --fps 30 >/dev/null 2>&1
    sleep 3
    out="$("$ROOT/pseye" status 2>&1)"
    fps="$(sed -n 's/.*(\([0-9]*\) fps).*/\1/p' <<<"$out")"
    if [[ -n "$fps" && "$fps" -ge 25 && "$fps" -le 35 ]]; then ok "--fps 30 gives ${fps} fps"; else bad "--fps 30 gave '${fps}'" "$out"; fi
    "$ROOT/pseye" off >/dev/null 2>&1
  fi
fi

# ---------------------------------------------------------------- summary

printf '\n%d passed, %d failed, %d skipped\n' "$pass" "$fail" "$skipped"
[[ $fail -eq 0 ]]
