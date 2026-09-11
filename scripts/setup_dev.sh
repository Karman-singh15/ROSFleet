#!/usr/bin/env bash
# One-time setup for the macOS-side development tools.
# These let you validate the robot model and run every unit test WITHOUT
# a ROS installation. ROS itself runs in Docker - see docker/README.md.
set -e
cd "$(dirname "$0")/.."

echo "Creating .venv ..."
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet xacro urdf-parser-py pytest pyserial pyyaml

echo
echo "Done. Run the checks with:"
echo "    ./scripts/run_tests.sh"
