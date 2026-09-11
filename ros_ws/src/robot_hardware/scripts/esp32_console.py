#!/usr/bin/env python3
"""
esp32_console.py - talk to the ESP32 by hand, with NO ROS running.

This is the tool you reach for the moment the robot misbehaves, because it
answers the only question that matters first: "is it the firmware or is it
ROS?"  It speaks the same protocol the bridge does.

    python3 esp32_console.py --serial /dev/ttyUSB0
    python3 esp32_console.py --tcp 192.168.1.50

Then type raw protocol lines:

    CMD,0.1,0        drive forward slowly
    CMD,0,0.5        spin left
    CMD,0,0          stop
    RST              zero the encoders
    PING,1           check the link

Everything the board sends is printed as it arrives. Ctrl-C sends a stop
command before exiting.
"""

import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))
from robot_hardware.esp32_link import SerialLink, TcpLink  # noqa: E402


def reader(link, stop):
    while not stop.is_set():
        try:
            for line in link.read_lines():
                print("  <- %s" % line)
        except Exception as exc:
            print("  !! link error: %s" % exc)
            stop.set()
            return
        time.sleep(0.01)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--serial", metavar="PORT", help="e.g. /dev/ttyUSB0")
    group.add_argument("--tcp", metavar="IP", help="e.g. 192.168.1.50")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()

    link = (SerialLink(args.serial, args.baud) if args.serial
            else TcpLink(args.tcp, args.port))
    print("connecting...")
    link.connect()
    print("connected. type protocol lines, or 'q' to quit.\n")

    stop = threading.Event()
    thread = threading.Thread(target=reader, args=(link, stop))
    thread.daemon = True
    thread.start()

    try:
        while not stop.is_set():
            line = input()
            if line.strip().lower() in ("q", "quit", "exit"):
                break
            if line.strip():
                link.send_line(line.strip())
                print("  -> %s" % line.strip())
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        stop.set()
        try:
            link.send_velocity(0.0, 0.0)   # never walk away from a moving robot
            time.sleep(0.1)
        except Exception:
            pass
        link.close()
        print("\nstopped and disconnected.")


if __name__ == "__main__":
    main()
