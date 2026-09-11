#!/usr/bin/env bash
# Run every check that works on macOS WITHOUT a ROS installation.
# This is the gate to pass before committing.
set -e
cd "$(dirname "$0")/.."

# Prefer the project venv (created by scripts/setup_dev.sh) so the checks
# have xacro/pytest available without touching the system Python.
if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python3
  echo "note: .venv not found - run ./scripts/setup_dev.sh first if checks fail"
  echo
fi

echo "=== URDF model ==="
$PY scripts/validate_urdf.py

echo
echo "=== XML well-formedness (launch / xacro / world) ==="
$PY - <<'PY'
import glob, sys, xml.dom.minidom
bad = 0
pats = ["ros_ws/src/**/*.xacro", "ros_ws/src/**/*.launch",
        "ros_ws/src/**/*.xml", "ros_ws/src/**/*.world"]
for pat in pats:
    for f in sorted(glob.glob(pat, recursive=True)):
        try:
            xml.dom.minidom.parse(f)
        except Exception as exc:
            bad += 1
            print("FAIL %s: %s" % (f, exc))
print("PASS: all XML well-formed" if not bad else "%d bad files" % bad)
sys.exit(1 if bad else 0)
PY

echo
echo "=== geometry consistency (URDF / hardware.yaml / firmware config.h) ==="
$PY scripts/check_geometry_sync.py

echo
echo "=== ESP32 firmware logic (compiled natively) ==="
./scripts/test_firmware.sh

echo
echo "=== unit tests ==="
$PY -m pytest ros_ws/src/robot_hardware/test -q

echo
echo "All checks passed."
