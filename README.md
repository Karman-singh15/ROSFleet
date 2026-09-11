# ROSFleet

An autonomous mobile robot with a web-based fleet management platform.

A ROS1 navigation stack that runs identically in Gazebo and on a physical
ESP32-driven chassis, a FastAPI backend, and a Next.js dashboard from which
you can say *"send RB001 to the AI Lab"* and watch it happen.

```
   Website  ──>  Backend  ──>  Mission Manager  ──>  move_base  ──>  /cmd_vel
                                                                        │
                                                        ┌───────────────┴───────────────┐
                                                        │                               │
                                                     Gazebo                       ESP32 + motors
                                                  (simulation)                     (real robot)
```

The whole project rests on one idea: **the robot is defined by a set of ROS
topics, not by its hardware.** `robot_bringup/launch/sim.launch` and
`real.launch` differ by exactly one line.

---

## Documentation

| Document | What it is for |
|---|---|
| **[docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md)** | How the whole system works, from the button on the website to the voltage on a motor pin. Read this first. |
| **[docs/HARDWARE_INTEGRATION.md](docs/HARDWARE_INTEGRATION.md)** | Step-by-step guide to connecting the physical robot, with a check at every stage. |
| **[docs/PROGRESS.md](docs/PROGRESS.md)** | Running implementation log: what is built, what was decided and why, what is next. |

---

## Quick start

### 1. macOS-side tooling (no ROS required)

```bash
./scripts/setup_dev.sh
./scripts/run_tests.sh
```

This validates the robot model, the cross-layer geometry constants, every
launch reference, the navigation configuration, the destinations, the
firmware logic (compiled natively), and runs the unit tests — in about two
seconds, without ROS.

### 2. The robotics stack (Docker)

ROS1 does not run natively on macOS, so it lives in a container with a
browser-based desktop.

```bash
docker compose up -d ros
open http://localhost:6080          # Gazebo and RViz, in a browser
docker compose exec ros bash
catkin_make && source devel/setup.bash
roslaunch robot_bringup sim.launch
```

Then drag a **2D Nav Goal** in RViz, or:

```bash
rosservice call /start_mission "{mission_id: 1, destination_name: 'AI Lab',
  goal_x: 3.8, goal_y: 3.4, goal_yaw: 1.57, preempt: false}"
```

### 3. The real robot

```bash
roslaunch robot_bringup real.launch transport:=serial
```

Work through [docs/HARDWARE_INTEGRATION.md](docs/HARDWARE_INTEGRATION.md)
first — the wheel-direction and encoder-sign checks in particular.

---

## Layout

```
rosfleet/
├── ros_ws/src/
│   ├── robot_description/   URDF: what the robot physically is
│   ├── robot_gazebo/        simulation world and spawn
│   ├── robot_hardware/      ROS <-> ESP32 bridge  (the HAL)
│   ├── robot_navigation/    move_base, AMCL, gmapping, costmaps
│   ├── mission_manager/     "go to the AI Lab" -> navigation goals
│   └── robot_bringup/       top-level launch files
│
├── firmware/esp32_robot/    ESP32: PWM, encoders, PID, protocol
├── backend/                 FastAPI + PostgreSQL        (not started)
├── frontend/                Next.js dashboard           (not started)
│
├── docker/                  ROS Noetic + Gazebo + noVNC image
├── maps/                    occupancy grids
├── scripts/                 validators and the test runner
└── docs/                    the three documents above
```

---

## The topic contract

Everything above the hardware layer is written against these, and only these:

| Topic | Type | Meaning |
|---|---|---|
| `/cmd_vel` | `geometry_msgs/Twist` | drive at this velocity |
| `/odom` | `nav_msgs/Odometry` | how far I have moved |
| `/scan` | `sensor_msgs/LaserScan` | what I can see around me |
| `/tf` | `tf2_msgs/TFMessage` | where my parts are |

Gazebo produces them. The ESP32, through `robot_hardware`, produces them.
Nothing else cares which.

---

## Current state

Phases 1–7 are implemented and covered by automated checks; the Docker
environment is written but not yet built; backend and frontend are not
started. Nothing has yet run inside a real ROS master or on physical
hardware.

See [docs/PROGRESS.md](docs/PROGRESS.md) for the detailed status, the
decision record, and the open risks.
