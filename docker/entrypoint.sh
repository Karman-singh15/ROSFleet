#!/usr/bin/env bash
# Container entrypoint: prepare the VNC desktop, then hand off to the
# command (supervisord by default, or a shell when you docker exec in).
set -e

source /opt/ros/noetic/setup.bash

# First-run VNC setup. Kept idempotent so a container restart is cheap.
if [ ! -f /root/.vnc/passwd ]; then
    mkdir -p /root/.vnc
    # No password: this listens only on localhost via the published port,
    # and typing a VNC password into a browser every restart is friction
    # with no security benefit here. Do NOT expose port 6080 publicly.
    echo "rosfleet" | vncpasswd -f > /root/.vnc/passwd
    chmod 600 /root/.vnc/passwd

    cat > /root/.vnc/xstartup <<'XEOF'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec startxfce4
XEOF
    chmod +x /root/.vnc/xstartup
fi

# Build the workspace if it has never been built. Subsequent builds are
# yours to run, so an accidental restart does not trigger a 5 minute wait.
if [ -d /root/rosfleet_ws/src ] && [ ! -d /root/rosfleet_ws/devel ]; then
    echo "First run: building the catkin workspace..."
    cd /root/rosfleet_ws
    catkin_make || echo "catkin_make failed - run it by hand to see why"
fi

if [ -f /root/rosfleet_ws/devel/setup.bash ]; then
    source /root/rosfleet_ws/devel/setup.bash
fi

exec "$@"
