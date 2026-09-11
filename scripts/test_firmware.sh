#!/usr/bin/env bash
# Compile and run the ESP32 firmware's hardware-independent logic natively.
# No ESP32, no PlatformIO, no ROS required.
set -e
cd "$(dirname "$0")/.."
OUT=$(mktemp -d)/firmware_tests
g++ -std=c++11 -Wall -Wextra -Werror -O2 \
    -o "$OUT" firmware/esp32_robot/test/test_native.cpp
"$OUT"
