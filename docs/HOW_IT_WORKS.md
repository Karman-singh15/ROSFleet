# How ROSFleet Works

A complete explanation of the system, from the button on the website down to
the voltage on a motor pin. Read this once end to end; after that use it as a
reference.

---

## Table of contents

1. [The one idea the whole project rests on](#1-the-one-idea-the-whole-project-rests-on)
2. [The six layers](#2-the-six-layers)
3. [ROS concepts you actually need](#3-ros-concepts-you-actually-need)
4. [The topic contract](#4-the-topic-contract)
5. [Frames and TF](#5-frames-and-tf)
6. [The robot model (URDF)](#6-the-robot-model-urdf)
7. [Simulation](#7-simulation)
8. [The hardware abstraction layer](#8-the-hardware-abstraction-layer)
9. [Odometry: how the robot knows it moved](#9-odometry-how-the-robot-knows-it-moved)
10. [Making a map](#10-making-a-map)
11. [Localisation: AMCL](#11-localisation-amcl)
12. [Navigation: move_base](#12-navigation-move_base)
13. [Missions](#13-missions)
14. [The backend](#14-the-backend)
15. [The frontend](#15-the-frontend)
16. [A mission, traced end to end](#16-a-mission-traced-end-to-end)
17. [What happens when things go wrong](#17-what-happens-when-things-go-wrong)
18. [How to run everything](#18-how-to-run-everything)

---

## 1. The one idea the whole project rests on

Everything in this project follows from a single decision:

> **The robot is defined by a set of ROS topics, not by its hardware.**

A "robot", to every piece of software above the lowest layer, is something
that:

- **accepts** `/cmd_vel` — "drive at this speed, turn at this rate"
- **publishes** `/odom` — "this is how far I have moved"
- **publishes** `/scan` — "this is what I can see around me"
- **publishes** `/tf` — "this is where my parts are relative to each other"

That is the entire definition. Nothing above that layer knows or cares
whether those topics are produced by Gazebo running physics on your Mac or
by an ESP32 driving two plastic gearmotors.

```
                    ┌───────────────────────────────┐
                    │  navigation, missions,        │
                    │  backend, website, analytics  │
                    └───────────────┬───────────────┘
                                    │
                    ══════════════════════════════════
                     /cmd_vel  /odom  /scan  /tf
                          THE CONTRACT
                    ══════════════════════════════════
                                    │
                 ┌──────────────────┴──────────────────┐
                 │                                     │
        ┌────────▼────────┐                   ┌────────▼────────┐
        │     Gazebo      │                   │  ESP32 + motors │
        │  (simulation)   │                   │  (real robot)   │
        └─────────────────┘                   └─────────────────┘
```

The practical consequence: `robot_bringup/launch/sim.launch` and
`robot_bringup/launch/real.launch` differ by **exactly one line** — which of
those two boxes gets started. Open them side by side and check; that
difference is the payoff for everything else in this document.

---

## 2. The six layers

```
┌──────────────────────────────────────────────────────────────┐
│ 6. WEB APPLICATION            Next.js + TypeScript           │
│    Dashboard, robots, maps, missions, analytics, logs        │
└────────────────────────────┬─────────────────────────────────┘
                             │  REST + WebSocket (JSON)
┌────────────────────────────▼─────────────────────────────────┐
│ 5. BACKEND                    FastAPI + PostgreSQL           │
│    Who the robots are, what the destinations mean, mission   │
│    history, analytics. The only component with a database.   │
└────────────────────────────┬─────────────────────────────────┘
                             │  rosbridge WebSocket + services
┌────────────────────────────▼─────────────────────────────────┐
│ 4. MISSION LAYER              mission_manager (ROS node)     │
│    "Go to the AI Lab" -> a move_base goal -> progress events │
└────────────────────────────┬─────────────────────────────────┘
                             │  actionlib
┌────────────────────────────▼─────────────────────────────────┐
│ 3. NAVIGATION                 move_base, AMCL, map_server    │
│    Path planning, obstacle avoidance, localisation           │
└────────────────────────────┬─────────────────────────────────┘
                             │  /cmd_vel  /odom  /scan  /tf
┌────────────────────────────▼─────────────────────────────────┐
│ 2. ROBOT INTERFACE            Gazebo  |  robot_hardware      │
│    Turns velocity commands into motion and motion into odom  │
└────────────────────────────┬─────────────────────────────────┘
                             │  serial / Wi-Fi, ASCII protocol
┌────────────────────────────▼─────────────────────────────────┐
│ 1. FIRMWARE                   ESP32                          │
│    PWM, H-bridge, encoders, battery ADC                      │
└──────────────────────────────────────────────────────────────┘
```

Each layer talks only to its neighbours. That is what makes the system
debuggable: when something misbehaves you can bisect by layer instead of
staring at the whole thing.

---

## 3. ROS concepts you actually need

ROS has a large vocabulary. You need five words.

### Node
A single program that does one job. `hardware_bridge` is a node. `move_base`
is a node. They run as separate processes and can be started, stopped and
crashed independently.

### Topic
A named, typed, one-way broadcast channel. Publishers write, subscribers
read, nobody waits for anybody.

```
  hardware_bridge ──publishes──> /odom ──> move_base
                                       ──> mission_manager
                                       ──> AMCL
```

Three subscribers, and the publisher does not know any of them exist. This
is why you can attach the backend to a running robot without modifying the
robot.

### Message
The type carried on a topic. `/cmd_vel` carries `geometry_msgs/Twist`:

```
linear:  {x: 0.30, y: 0.0, z: 0.0}     # x = forward, m/s
angular: {x: 0.0,  y: 0.0, z: 0.45}    # z = turn rate, rad/s
```

A differential-drive robot can only use `linear.x` and `angular.z` — it
cannot move sideways, so `linear.y` is always zero.

### Service
A request/response call, like a function. Used when you need an answer:
`/start_mission` is a service because the caller must know whether the
mission was accepted.

### Action
A long-running request with progress updates and the ability to cancel.
Navigation is an action: it takes 40 seconds, you want feedback while it
runs, and you need to be able to abort. `move_base` exposes an action;
`mission_manager` is its client.

```
   mission_manager ──goal──────────> move_base
                   <──feedback────
                   <──feedback────
                   <──result──────   SUCCEEDED / ABORTED / PREEMPTED
```

---

## 4. The topic contract

These are fixed. Treat changing one as a breaking change to the whole
project.

| Topic | Type | Direction | Meaning |
|---|---|---|---|
| `/cmd_vel` | `geometry_msgs/Twist` | into the robot | drive at this velocity |
| `/odom` | `nav_msgs/Odometry` | out of the robot | how far I have moved, and how fast |
| `/scan` | `sensor_msgs/LaserScan` | out of the robot | distances to everything around me |
| `/joint_states` | `sensor_msgs/JointState` | out of the robot | wheel angles, for RViz |
| `/tf` | `tf2_msgs/TFMessage` | out of the robot | where my frames are |
| `/map` | `nav_msgs/OccupancyGrid` | from map_server | the floor plan |
| `/robot_telemetry` | `robot_hardware/RobotTelemetry` | out of the robot | battery, link health, ticks |
| `/hardware_connected` | `std_msgs/Bool` | out of the robot | is the ESP32 alive |
| `/mission_status` | `mission_manager/MissionStatus` | out of mission_manager | current mission + progress |
| `/mission_events` | `mission_manager/MissionEvent` | out of mission_manager | timestamped log lines |

**`/cmd_vel` is the single most important one.** It is the only channel
through which anything can make the robot move. If the robot is moving,
something is publishing to `/cmd_vel`; if it is not moving, either nothing
is publishing or the layer below is refusing. That one fact resolves a large
fraction of all robot debugging:

```bash
rostopic echo /cmd_vel        # is anything commanding motion?
rostopic hz /cmd_vel          # at what rate?
```

---

## 5. Frames and TF

A robot is a collection of coordinate frames, and TF is the system that
tracks how they relate over time. Getting this right is most of getting
navigation right.

```
   map                     fixed to the building; never moves
    │
    │  published by AMCL — "the correction"
    ▼
   odom                    fixed to where the robot booted; drifts slowly
    │
    │  published by the odometry source (Gazebo or hardware_bridge)
    ▼
   base_footprint          the robot's position on the floor
    │
    ▼
   base_link               the chassis centre
    ├── left_wheel_link
    ├── right_wheel_link
    ├── caster_link
    └── laser_link         the LiDAR's optical centre; /scan is in this frame
```

### Why two frames instead of one

This trips up nearly everyone, so it is worth being precise.

**`odom`** is *smooth but wrong*. It comes from counting wheel rotations. It
never jumps, so it is safe to use for local control. But wheels slip, and
the error accumulates forever — after ten minutes of driving, odometry might
think the robot is two metres from where it really is.

**`map`** is *correct but jumpy*. AMCL compares the live laser scan against
the stored floor plan and works out where the robot really is. It is
globally accurate, but the answer can jump by tens of centimetres the moment
new evidence arrives.

You need both:

- The **local costmap** uses `odom`, because a jump would make an obstacle
  appear to teleport, and the robot would swerve at nothing.
- The **global costmap and goals** use `map`, because "the AI Lab" is a fixed
  place in the building, not a place relative to where you happened to boot.

AMCL bridges them by publishing `map -> odom`: not the robot's position, but
**the accumulated error in the odometry**. As drift grows, that transform
grows to cancel it.

```
   true position  =  map->odom  ∘  odom->base_footprint
                     (correction)   (dead reckoning)
```

### Debugging TF

```bash
rosrun tf view_frames      # writes frames.pdf — a picture of the tree
rosrun tf tf_echo map base_footprint    # where does ROS think the robot is?
rosrun rqt_tf_tree rqt_tf_tree          # live view
```

**The tree must have exactly one root and no gaps.** Two nodes publishing the
same transform is the classic failure — usually Gazebo's diff-drive plugin
*and* `hardware_bridge` both publishing `odom -> base_footprint`. The
transform then flickers between two answers and navigation behaves
erratically. This is exactly why `real.launch` loads the URDF with
`use_gazebo:=false`.

---

## 6. The robot model (URDF)

`robot_description` answers "what is this robot, physically?" — in one place,
used by everything.

```
ros_ws/src/robot_description/urdf/
├── common_properties.xacro   every dimension, as named constants
├── robot.urdf.xacro          links and joints
└── robot.gazebo.xacro        simulation-only plugins
```

**Xacro** is XML with macros and arithmetic. It exists because a raw URDF
repeats itself horribly — describing a left and right wheel means writing the
same 20 lines twice, with one sign flipped. In xacro:

```xml
<xacro:drive_wheel prefix="left"  reflect="1"/>
<xacro:drive_wheel prefix="right" reflect="-1"/>
```

**Every physical number lives in `common_properties.xacro`.** When you build
the real chassis, you measure it and change the numbers there. The wheel
positions, the Gazebo plugin's wheel separation, the navigation footprint and
the TF tree all follow automatically.

Three of those numbers also appear in `hardware.yaml` (host) and `config.h`
(firmware), because those files cannot read xacro.
`scripts/check_geometry_sync.py` fails the build if they ever disagree — a
mismatch there makes the robot turn the wrong amount and looks exactly like
a navigation bug.

Check the model without starting anything:

```bash
python3 scripts/validate_urdf.py        # on macOS, no ROS needed
roslaunch robot_description view_model.launch   # in the container, visual
```

---

## 7. Simulation

Gazebo is a physics engine. Given the URDF, it simulates gravity, friction,
motor torque and collisions, and runs a simulated LiDAR that ray-casts
against the world geometry.

Two plugins do all the work of standing in for your electronics:

| Plugin | Stands in for |
|---|---|
| `libgazebo_ros_diff_drive` | motor driver + encoders + odometry maths |
| `libgazebo_ros_laser` | RPLiDAR + its ROS driver |

`odometrySource` is set to `encoder`, not `world`. Gazebo *could* hand you
the robot's exact position — it is a simulation, it knows. Using simulated
encoders instead means simulated odometry **drifts when the wheels slip**,
just like the real thing. If AMCL cannot cope with your simulated drift, it
will not cope with real drift either, and you want to find that out on your
laptop.

The world (`worlds/lab.world`) is a 10 × 8 m room with partitions and
furniture. Replace it with your actual college floor plan later; nothing else
changes.

---

## 8. The hardware abstraction layer

One node, `hardware_bridge`, is the **only** software in the project that
knows the robot contains an ESP32.

```
   /cmd_vel  ──>┐                                    ┌──> motors
                │   hardware_bridge  ⇄  ESP32        │
   /odom    <───┤   (Python, on the   serial/Wi-Fi   ├──< encoders
   /tf      <───┤    Mac or a Pi)                    │
   telemetry <──┘                                    └──< battery
```

### The protocol

Deliberately plain ASCII, one message per line:

```
Mac -> ESP32                     ESP32 -> Mac
  CMD,0.300,-0.150                 ENC,15204,15198,48320
  PING,42                          BAT,7.82
  RST                              DIST,42.0
  CFG,kp,1.2                       PONG,42
                                   VER,esp32-1.0.0
                                   ERR,watchdog expired
```

Four decisions here matter more than they look:

**Text, not binary.** You can debug it with a serial monitor, with `nc`, or by
typing into `esp32_console.py`. A binary protocol saves bandwidth you do not
need and costs you the ability to see what is happening.

**Cumulative tick counts, not deltas.** If a line is dropped, a delta
protocol loses that motion *permanently* and odometry is wrong forever.
With cumulative counts the next message carries the absolute truth and the
error self-heals.

**The ESP32 timestamps its own messages.** Velocity is `ticks / dt`. If `dt`
came from the Mac's clock it would include Wi-Fi jitter, and the measured
velocity would be noise. Using the ESP32's own `millis()` makes the
measurement immune to link latency.

**Both sides clamp, both sides have a watchdog.** The bridge stops the robot
if `/cmd_vel` goes stale; the firmware stops the motors if `CMD` goes stale.
Either one alone is a robot that drives into a wall when the other fails.

### Testing it without hardware

`transport: loopback` runs a simulated ESP32 *inside the bridge process*,
integrating commanded velocity into encoder ticks. You get the complete real
robot pipeline — bridge, protocol, odometry, TF — with no board attached:

```bash
rosrun robot_hardware hardware_bridge.py _transport:=loopback
```

---

## 9. Odometry: how the robot knows it moved

The wheels have encoders. Each encoder tick is a known fraction of a wheel
rotation, and a wheel rotation is a known distance:

```
   distance per tick = 2 π r / ticks_per_rev
                     = 2 π × 0.0325 / 780
                     = 0.000262 m          (about a quarter of a millimetre)
```

For a differential drive, from the two wheel distances:

```
   d_centre = (d_left + d_right) / 2            how far the robot moved
   d_theta  = (d_right - d_left) / L            how far it turned
```

Then integrate. This implementation uses the **exact arc**, not the common
straight-line approximation:

```python
if abs(d_theta) < 1e-6:            # essentially straight
    x += d_centre * cos(theta)
    y += d_centre * sin(theta)
else:                              # arc of radius R
    R = d_centre / d_theta
    x += R * (sin(theta + d_theta) - sin(theta))
    y -= R * (cos(theta + d_theta) - cos(theta))
theta += d_theta
```

The approximation assumes the robot travels in a straight line between
samples. Over a tight indoor turn that error accumulates quickly. The exact
version costs two extra trig calls and is in
`robot_hardware/src/robot_hardware/odometry.py`, with tests that fail if
anyone "simplifies" it back.

### Odometry always lies eventually

Wheels slip. The robot is pushed. A wheel goes over a cable. None of that
shows up in the encoder counts, so the error only ever grows. Odometry is
excellent over seconds and worthless over minutes — which is precisely why
AMCL exists.

This is also why `/odom`'s covariance matrix is set the way it is: small
values for `x` and `yaw` (measured, roughly trusted), enormous values for
`y`, `z`, `roll`, `pitch` (a differential drive cannot observe them at all).
AMCL reads those numbers to decide how much to believe the odometry.

---

## 10. Making a map

Before a robot can navigate a building, it needs a floor plan. You build one
once per floor, with SLAM.

```
   1. Start the robot (simulated or real)
   2. roslaunch robot_navigation mapping.launch
   3. Drive it slowly around every corridor, with teleop
   4. rosrun map_server map_saver -f ~/floor1
```

`gmapping` listens to `/scan` and `/odom` and does two things at once: builds
the map, and figures out where the robot is in the map it is building. That
circularity is what "SLAM" means — Simultaneous Localisation And Mapping.

You get two files:

```
   floor1.pgm    a greyscale image: black = wall, white = free, grey = unknown
   floor1.yaml   resolution (m per pixel) and the origin's world coordinates
```

Practical advice that will save you an afternoon:

- **Drive slowly.** Fast turns slip the wheels, odometry lies, and gmapping
  bends straight corridors into curves.
- **Close the loop.** Return to where you started. gmapping recognises the
  place and corrects accumulated drift across the whole map.
- **Cover every space you want to navigate.** Unmapped space is
  "unknown", and the global planner is configured with
  `allow_unknown: false` — it will not plan through it.

For simulation you do not have to do this at all:
`scripts/generate_sim_map.py` derives a perfect map from the Gazebo world
geometry, so you can test navigation on day one. Do the real thing when you
have the real robot.

---

## 11. Localisation: AMCL

**Adaptive Monte Carlo Localisation.** The question it answers: *given this
map and this laser scan, where am I?*

It works with **particles** — each one a hypothesis "the robot might be here,
facing this way".

```
   1. Scatter particles over the plausible area
   2. The robot moves ->  move every particle the same way, plus noise
                          (noise because odometry is not exact)
   3. A scan arrives  ->  for each particle, ask: "if the robot were HERE,
                          would the laser see THIS?"
   4. Score particles by how well they agree with the scan
   5. Resample: keep the good hypotheses, discard the bad ones
   6. Repeat
```

Particles converge on the truth because only the correct position explains
the scan consistently as the robot moves.

```
  start: scattered            after a few metres: converged
  · ·  ·   ·  ·                         ·
   ·  · ·  · ·                         ···
  ·  ·   ·  ·  ·                      ·····
   · ·  ·  · ·                         ···
```

The two settings you will actually adjust:

- **`odom_alpha1..4`** — how much your odometry lies. Set higher than the ROS
  defaults here, because cheap plastic gearboxes slip. If AMCL keeps
  snapping the robot to the wrong place, raise these before anything else.
- **`min/max_particles`** — more particles is more robust and more CPU. 300
  to 2500 is right for a small indoor robot.

AMCL needs a starting guess. In simulation it comes from the launch file; on
the real robot you give it with RViz's *2D Pose Estimate* tool, or the
website's "set initial pose". **A wrong initial pose is the single most
common reason a real robot refuses to navigate** — it is trying to reach a
place it thinks is on the other side of a wall.

---

## 12. Navigation: move_base

`move_base` accepts a goal pose and drives there. Inside it there are four
pieces.

```
                   goal (x, y, yaw in the map frame)
                                 │
          ┌──────────────────────▼──────────────────────┐
          │                 move_base                   │
          │                                             │
          │   GLOBAL PLANNER        LOCAL PLANNER       │
          │   Dijkstra over the     DWA: simulate many  │
          │   whole map -> a route  short trajectories, │
          │                         pick the best one   │
          │        │                        │           │
          │   GLOBAL COSTMAP        LOCAL COSTMAP       │
          │   the static map        3×3 m moving window │
          │   + inflation           + live laser        │
          └──────────────────────┬──────────────────────┘
                                 │
                             /cmd_vel
```

### Costmaps

A costmap is the map with a cost per cell: 0 is free, 254 is "the robot's
centre cannot be here". **Inflation** grows obstacles by roughly the robot's
radius, so a planner that treats the robot as a point still produces paths
the real robot fits through.

This is the setting most worth understanding, because getting it wrong is
silent:

- **Too large** → doorways seal shut. The planner reports "no path" and the
  robot sits still with nothing visibly in the way.
- **Too small** → the robot clips door frames and corners.

Here it is `0.22 m` against a circumscribed robot radius of `0.142 m`, which
leaves 0.31 m of free space in a 0.75 m doorway.
`scripts/check_nav_config.py` verifies that arithmetic so you cannot
accidentally seal your own building.

### Global planner

Dijkstra over the global costmap. Runs about twice a second. Produces the
green line you see in RViz — a route that ignores anything not on the stored
map.

### Local planner (DWA)

*Dynamic Window Approach*, running at 5 Hz:

```
   1. Sample many (linear, angular) velocity pairs the robot could
      physically reach in the next instant
   2. Simulate each one forward for sim_time (2 s)
   3. Score each resulting trajectory:
        - does it stay close to the global path?   (path_distance_bias)
        - does it get closer to the goal?          (goal_distance_bias)
        - does it stay away from obstacles?        (occdist_scale)
   4. Publish the winner as /cmd_vel
   5. Throw everything away and repeat
```

DWA is what actually avoids the chair someone just moved: the chair is in
the local costmap from the live laser, so every trajectory through it scores
terribly.

**The velocity limits in `dwa_local_planner.yaml` must not exceed what the
robot can really do.** Tell DWA the robot does 1.0 m/s when the motors
saturate at 0.35 and every plan it makes is a lie: the robot lags behind its
own trajectory, overshoots corners, then oscillates. It looks like bad PID
tuning. It is not. `check_nav_config.py` enforces this against
`hardware.yaml`.

### Recovery behaviours

When the robot gets stuck, move_base escalates:

```
   stuck -> clear the costmaps (drop stale obstacles)
         -> rotate in place (look around, refill the costmap)
         -> clear more aggressively
         -> give up, return ABORTED
```

That `ABORTED` becomes a `FAILED` mission, which becomes a red row on the
website's analytics page.

---

## 13. Missions

`move_base` thinks in coordinates. People think in places. `mission_manager`
is the translator, and the seam between the robotics stack and the web app.

```
   Website:   [ RB001 ] → [ AI Lab ]  [DEPLOY]
                          │
   Backend:   look up "AI Lab" in the destinations table
              → (x=3.8, y=3.4, yaw=1.57)
              → create mission row #104, status QUEUED
                          │
              call /start_mission {mission_id: 104, goal_x: 3.8, ...}
                          │
   mission_manager: send the goal to move_base, track it
                          │
   move_base:  plan, drive, avoid, arrive
                          │
   mission_manager: publish /mission_status at 2 Hz
                          │
   Backend:   update row #104 → SUCCEEDED, distance, duration
                          │
   Website:   the progress bar fills, the row turns green
```

### Why this is a separate ROS node and not just backend code

- `actionlib` is a ROS-native protocol with its own handshake. Keeping it on
  the ROS side means the backend makes one plain service call.
- Progress tracking needs `/odom`, `/move_base/status` and the global plan at
  ROS rates. Doing that across a WebSocket bridge would be slow and lossy.
- **If the backend crashes mid-mission, the robot still finishes safely**,
  because the mission state lives in ROS, not in the API process.

### The state machine

```
   IDLE ──start──> QUEUED ──accepted──> NAVIGATING ──arrive──> SUCCEEDED
                     │                       │
                     │                       ├──fail────────> FAILED
                     └──cancel──────────────┴──cancel──────> CANCELLED
```

Terminal states are sticky: a mission that succeeded stays `SUCCEEDED` until
a new one starts. The dashboard keeps showing the outcome instead of
blanking to `IDLE` the instant the robot arrives — and a `cancel` that
arrives one tick *after* arrival cannot rewrite history. There is a test for
exactly that race, because it is the kind of thing that quietly corrupts
analytics for weeks.

---

## 14. The backend

FastAPI + PostgreSQL. It owns everything ROS does not:

- **identity** — which robots exist, what they are called, whether they are online
- **meaning** — that "AI Lab" is `(3.8, 3.4, 1.57)` on `floor1`
- **history** — every mission ever run, with its outcome and duration
- **analytics** — success rates, utilisation, failure breakdowns

It talks to ROS over `rosbridge`, a WebSocket server that exposes ROS topics
and services as JSON.

```
   FastAPI  ──ws://ros:9090──>  rosbridge  ──>  ROS
```

The database schema is in `docs/PROGRESS.md` as it gets built.

---

## 15. The frontend

Next.js + TypeScript + Tailwind. **It never talks to ROS.**

```
   GOOD                              BAD
   Next.js                           Next.js
     ↓  REST / WebSocket               ↓  roslibjs
   FastAPI                           ROS topics
     ↓
   ROS
```

The frontend posts:

```json
POST /api/missions
{ "robot_id": "RB001", "destination_id": 7 }
```

It does not know what `/cmd_vel` is, and it should not. That separation means
you can restructure the ROS side entirely without touching a line of React —
and it means the website still renders something sensible when the robot is
switched off.

---

## 16. A mission, traced end to end

Someone clicks **Deploy**. Here is the whole path.

```
 1.  Browser      POST /api/missions {robot_id: "RB001", destination_id: 7}

 2.  FastAPI      SELECT * FROM destinations WHERE id = 7
                  -> ("AI Lab", x=3.8, y=3.4, yaw=1.57)
                  INSERT INTO missions (...) -> id 104, status QUEUED

 3.  FastAPI      rosbridge call /start_mission
                  {mission_id: 104, goal_x: 3.8, goal_y: 3.4, goal_yaw: 1.57}

 4.  mission_mgr  tracker.start() -> QUEUED
                  actionlib send_goal to move_base
                  publish MissionEvent GOAL_SENT

 5.  move_base    global planner: Dijkstra over the costmap -> a route
                  local planner: DWA picks a trajectory
                  publish /cmd_vel {linear.x: 0.22, angular.z: -0.1}

 6a. SIMULATION   Gazebo applies torque, wheels turn, physics runs
                  publishes /odom, /scan, /tf

 6b. REAL ROBOT   hardware_bridge: "CMD,0.220,-0.100\n" over Wi-Fi
                  ESP32: inverse kinematics -> per-wheel rad/s
                         PID per wheel -> PWM duty
                         H-bridge -> motors turn
                         encoders count -> "ENC,15204,15198,48320\n"
                  hardware_bridge: ticks -> pose -> /odom + TF

 7.  AMCL         matches /scan against /map, publishes map->odom

 8.  mission_mgr  integrates /odom -> distance travelled
                  measures the remaining global plan -> percent complete
                  publishes /mission_status at 2 Hz

 9.  FastAPI      receives /mission_status over rosbridge
                  pushes it to the browser over a WebSocket

10.  Browser      progress bar fills: 41% ... 72% ... 96%

11.  move_base    within 0.15 m and 0.2 rad of the goal -> SUCCEEDED

12.  mission_mgr  tracker.succeed() -> MissionStatus SUCCEEDED
                  MissionEvent ARRIVED

13.  FastAPI      UPDATE missions SET status='SUCCEEDED',
                    completed_at=now(), distance=14.2, duration=38

14.  Browser      row turns green, analytics recompute
```

Step 6 is the only step that differs between simulation and reality. Every
other step is byte-for-byte identical.

---

## 17. What happens when things go wrong

The system is designed so that failures are visible rather than mysterious.

### The ESP32 disconnects mid-mission

```
   Wi-Fi drops
      │
      ├─ ESP32:           no CMD for 500 ms -> watchdog -> motors stop
      │                   (the robot halts even though nobody told it to)
      │
      └─ hardware_bridge: no ENC for 1 s -> /hardware_connected = false
              │
              └─ mission_manager: aborts the mission -> FAILED
                      │
                      └─ backend -> website:  🔴 RB001 OFFLINE
```

Both sides act independently. If the bridge crashes, the firmware watchdog
still stops the robot; if the firmware hangs, the bridge still reports the
robot as offline.

### The robot gets lost

AMCL's particles spread out (visible in RViz as a cloud instead of a tight
cluster). The robot may drive confidently to the wrong place. Fix: give it a
2D Pose Estimate. Prevent: raise `odom_alpha` values, make sure the map
matches the building, check the LiDAR is not blocked.

### move_base reports "no path"

Almost always one of:

- the goal is inside an obstacle or in unknown space
  (`scripts/check_destinations.py` catches this before you ever run)
- the inflation radius has sealed a doorway (`check_nav_config.py`)
- the robot's own position is wrong, so it believes it is walled in

### The robot turns too far / not far enough

The wheel separation in the firmware disagrees with reality or with the host.
Run `scripts/check_geometry_sync.py`, then re-measure the wheelbase. No
amount of PID tuning fixes a geometry error.

### Nothing moves at all

Bisect using the contract:

```bash
rostopic echo /cmd_vel      # is anything commanding motion?
```

- **Nothing published** → the problem is above: move_base, a bad goal, a
  missing map, AMCL not localised.
- **Published but no motion** → the problem is below: the bridge, the link,
  the firmware, the wiring, the battery.

One command, and you have halved the search space.

---

## 18. How to run everything

### Everything in simulation

```bash
docker compose up -d ros
open http://localhost:6080          # the desktop, in a browser
docker compose exec ros bash
roslaunch robot_bringup sim.launch
```

Then either drag a *2D Nav Goal* in RViz, or:

```bash
rosservice call /start_mission "{mission_id: 1, destination_name: 'AI Lab',
  goal_x: 3.8, goal_y: 3.4, goal_yaw: 1.57, preempt: false}"
```

### Everything on the real robot

```bash
roslaunch robot_bringup real.launch transport:=serial
```

See `docs/HARDWARE_INTEGRATION.md` first — particularly the wheel-direction
and encoder-sign checks, which must pass before you let the robot navigate.

### Checks, on macOS, without ROS

```bash
./scripts/run_tests.sh
```

URDF validity, XML well-formedness, geometry consistency across all three
layers, launch-file references, destination reachability, navigation config
sanity, the firmware's logic compiled natively, and the Python unit tests.
