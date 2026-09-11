#!/usr/bin/env bash
# Run every check that works on macOS WITHOUT a ROS installation.
# This is the gate to pass before committing.
set -e
cd "$(dirname "$0")/.."

echo "=== URDF model ==="
python3 scripts/validate_urdf.py

echo
echo "=== XML well-formedness (launch / xacro / world) ==="
python3 - <<'PY'
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
echo "=== unit tests ==="
python3 -m pytest ros_ws/src/robot_hardware/test -q

echo
echo "All checks passed."
