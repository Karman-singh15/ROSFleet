# =====================================================================
#  ROS1 Noetic + Gazebo 11 development container
#
#  ROS1 does not run natively on macOS, so the entire robotics stack lives
#  in here. Your Mac is the editor; this container is the robot's computer.
#
#  GUI (Gazebo, RViz) is served over noVNC, so you open it in a browser at
#  http://localhost:6080 - no XQuartz, no X11 forwarding headaches.
#
#  Built for arm64 (Apple Silicon) natively; the same file works on amd64.
# =====================================================================
FROM osrf/ros:noetic-desktop-full

ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=noetic

# ---------------------------------------------------------------- ROS deps
# Everything the launch files reference. Installed in one layer so a
# rebuild after editing source does not re-download all of this.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-noetic-navigation \
        ros-noetic-move-base \
        ros-noetic-amcl \
        ros-noetic-map-server \
        ros-noetic-gmapping \
        ros-noetic-dwa-local-planner \
        ros-noetic-global-planner \
        ros-noetic-costmap-2d \
        ros-noetic-teleop-twist-keyboard \
        ros-noetic-joint-state-publisher \
        ros-noetic-joint-state-publisher-gui \
        ros-noetic-robot-state-publisher \
        ros-noetic-xacro \
        ros-noetic-rosbridge-suite \
        ros-noetic-tf2-web-republisher \
        ros-noetic-rplidar-ros \
        ros-noetic-gazebo-ros-pkgs \
        ros-noetic-gazebo-ros-control \
        ros-noetic-rqt-graph \
        ros-noetic-rqt-plot \
        ros-noetic-rqt-tf-tree \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------ build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-catkin-tools \
        python3-pip \
        python3-rosdep \
        build-essential \
        git \
        vim \
        nano \
        less \
        iputils-ping \
        net-tools \
        usbutils \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir pyserial pyyaml

# ------------------------------------------------------------ VNC desktop
# TigerVNC gives a real X server; noVNC turns it into a web page.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tigervnc-standalone-server \
        tigervnc-common \
        novnc \
        websockify \
        xfce4 \
        xfce4-terminal \
        dbus-x11 \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

# xfce4's screensaver and power manager are pointless in a container and
# they fight with VNC; removing them avoids a black screen after 10 minutes.
RUN apt-get purge -y xfce4-screensaver xfce4-power-manager 2>/dev/null || true

# Gazebo on Apple Silicon has no GPU passthrough, so force software
# rendering. Without this Gazebo starts and then dies with a GL error.
ENV LIBGL_ALWAYS_SOFTWARE=1
ENV GALLIUM_DRIVER=llvmpipe
ENV QT_X11_NO_MITSHM=1

# Gazebo tries to download models from the internet on first run and stalls
# for minutes if the network is slow. Point it at the local model path.
ENV GAZEBO_MODEL_DATABASE_URI=""

ENV DISPLAY=:1
ENV VNC_RESOLUTION=1600x900
ENV VNC_PORT=5901
ENV NOVNC_PORT=6080

WORKDIR /root/rosfleet_ws

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY supervisord.conf /etc/supervisor/conf.d/rosfleet.conf
RUN chmod +x /usr/local/bin/entrypoint.sh

# Source ROS and the workspace in every interactive shell, so `docker exec`
# lands you in a working environment without remembering to source anything.
RUN echo 'source /opt/ros/noetic/setup.bash' >> /root/.bashrc && \
    echo '[ -f /root/rosfleet_ws/devel/setup.bash ] && source /root/rosfleet_ws/devel/setup.bash' >> /root/.bashrc && \
    echo 'export ROS_MASTER_URI=http://localhost:11311' >> /root/.bashrc && \
    echo 'cd /root/rosfleet_ws' >> /root/.bashrc

EXPOSE 6080 5901 9090 11311

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]
