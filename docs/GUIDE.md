# ROSFleet: The Complete Guide

Everything you need to run this project, understand what it does, know where
the traps are, and decide what to build next.

Read this first. The other documents go deeper:

| Document | When to read it |
|---|---|
| **This guide** | Now. Orientation, running it, features, what to know, what to build next |
| [HOW_IT_WORKS.md](HOW_IT_WORKS.md) | When you want the technical detail behind any layer |
| [HARDWARE_INTEGRATION.md](HARDWARE_INTEGRATION.md) | The day your parts arrive |
| [PROGRESS.md](PROGRESS.md) | To see what is built, what was decided and why |

---

## Contents

1. [What this project actually is](#1-what-this-project-actually-is)
2. [How it works, step by step](#2-how-it-works-step-by-step)
3. [Running it](#3-running-it)
4. [Feature list](#4-feature-list)
5. [Things you should know](#5-things-you-should-know)
6. [How to work on it](#6-how-to-work-on-it)
7. [What to improve, in priority order](#7-what-to-improve-in-priority-order)
8. [Presenting it](#8-presenting-it)
9. [Quick reference](#9-quick-reference)

---

## 1. What this project actually is

Three things that fit together:

1. **A robot that can drive itself to a named place** — "go to the AI Lab" —
   using a map, a laser scanner and a navigation stack.
2. **A web application to command and monitor it** — deploy missions, watch
   live progress, see history and analytics.
3. **An architecture where the simulated robot and the physical robot are
   interchangeable.**

Point 3 is the one that matters, and it is worth being precise about why.

### The idea the whole project rests on

The robot is defined by **a set of ROS topics**, not by its hardware. To
everything above the lowest layer, a "robot" is anything that:

- accepts `/cmd_vel` — "drive at this speed, turn at this rate"
- publishes `/odom` — "this is how far I have moved"
- publishes `/scan` — "this is what I can see around me"

Gazebo satisfies that contract. An ESP32 driving two gearmotors satisfies it
too. So navigation, missions, the backend and the website are written once
and work with either.

The proof is in the repository. Open `robot_bringup/launch/sim.launch` and
`real.launch` side by side: navigation, the mission manager and rosbridge are
included **identically** in both. Only the bottom layer swaps — Gazebo in one,
the hardware bridge plus the real LiDAR driver in the other.

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
        ┌────────▼────────┐                   ┌────────▼────────┐
        │     Gazebo      │                   │  ESP32 + motors │
        └─────────────────┘                   └─────────────────┘
```

### Why that is worth doing

Because you can build **almost the entire project before the hardware
exists**, and when it arrives you are not "building the robot project" — you
are implementing the physical backend for a robot that already works.

That is exactly the state this repository is in right now.

---

## 2. How it works, step by step

Someone opens the website and clicks **Deploy**. Here is everything that
happens, in order.

### Step 1 — The browser asks the backend

```json
POST /api/missions
{ "robot_id": 1, "destination_id": 7 }
```

The browser knows about robots and destinations. It does not know what
`/cmd_vel` is, and it never will.

### Step 2 — The backend turns a name into a place

```sql
SELECT * FROM destinations WHERE id = 7;
-- ("AI Lab", x = 3.8, y = 3.4, yaw = 1.57)
```

**This is the translation that makes the whole product usable.** People think
in places; robots think in coordinates. The database is where one becomes the
other.

The backend writes a mission row (status `QUEUED`) and gets back an id — say
`104`. That id is then used by *both* sides, so there is never any confusion
about which mission is which.

### Step 3 — The backend asks ROS to do it

```
/start_mission  {mission_id: 104, goal_x: 3.8, goal_y: 3.4, goal_yaw: 1.57}
```

One service call, over a WebSocket (`rosbridge`). Notice what does not cross
this boundary: no database, no names, no HTTP. ROS receives a pose.

### Step 4 — The mission manager hands it to the navigation stack

`mission_manager` sends the pose to `move_base` as an **actionlib goal** — a
long-running request that reports progress and can be cancelled. It then
tracks that mission: how far along it is, how far it has driven, what
happened and when.

### Step 5 — Navigation plans a route

```
      goal (3.8, 3.4)
            │
   ┌────────▼─────────────────────────────┐
   │            move_base                 │
   │                                      │
   │  GLOBAL PLANNER      LOCAL PLANNER   │
   │  Dijkstra over       DWA: simulate   │
   │  the whole map       many short      │
   │  → a route           paths, pick one │
   │       │                    │         │
   │  GLOBAL COSTMAP      LOCAL COSTMAP   │
   │  stored map +        3×3 m window +  │
   │  inflation           live laser      │
   └────────────────────┬─────────────────┘
                        │
                    /cmd_vel
```

The **global planner** finds a route across the building. The **local
planner** (DWA) runs five times a second: it simulates dozens of short
trajectories the robot could physically take, scores each on "does it follow
the route, does it approach the goal, does it avoid obstacles", and publishes
the winner as a velocity command.

That is what dodges the chair somebody just moved — the chair is in the local
costmap from the live laser, so every path through it scores terribly.

### Step 6 — Something executes the velocity

**This is the only step that differs between simulation and reality.**

```
  SIMULATION                      REAL ROBOT
  ──────────                      ──────────
  Gazebo applies torque           hardware_bridge sends "CMD,0.220,-0.100"
  wheels turn in physics          ESP32 converts to per-wheel speeds
  simulated encoders count        PID drives the H-bridge
                                  motors turn, encoders count
                                  ESP32 sends "ENC,15204,15198,48320"
                                  hardware_bridge integrates it into a pose
         │                                │
         └────────────┬───────────────────┘
                      ▼
           /odom, /scan, /tf  — identical either way
```

### Step 7 — The robot works out where it really is

Wheel odometry drifts — wheels slip, and the error only ever grows. So
**AMCL** compares the live laser scan against the stored map hundreds of
times, using a cloud of "maybe the robot is here" particles, and publishes a
correction.

```
   where you really are  =  AMCL's correction  ∘  wheel odometry
                            (accurate, jumpy)     (smooth, drifting)
```

### Step 8 — Progress flows back to the screen

```
  mission_manager  →  /mission_status (2 Hz)
        ↓
  backend updates mission row 104
        ↓
  WebSocket push
        ↓
  browser: progress bar 41% … 72% … 96%
```

### Step 9 — Arrival

`move_base` reports `SUCCEEDED` once inside 15 cm and 0.2 rad of the goal.
The mission row is completed with its distance and duration, the robot
returns to `IDLE`, and the analytics recompute.

If it fails instead — no path, stuck after recovery, robot disconnected — the
row records **why**, and the failure appears on the analytics page bucketed
by cause.

---

## 3. Running it

There are three things you can run, and they are independent. **You do not
need all three at once**, which is the point.

| I want to… | Run | Needs |
|---|---|---|
| Check I have not broken anything | the test suite | nothing but Python |
| Work on the website | backend + frontend | Python + Node |
| Drive a robot around | Docker + ROS | Docker |

### 3.1 First-time setup

```bash
cd "~/Documents/robot project"
./scripts/setup_dev.sh
```

Creates `.venv` and installs everything Python-side. One minute, once.

### 3.2 Run the checks (2 seconds, no ROS, no robot)

```bash
./scripts/run_tests.sh
```

This is your safety net. It validates the robot model, checks the drivetrain
numbers agree across all three files that hold them, resolves every launch
file reference, confirms each destination is somewhere the robot can stand,
sanity-checks the navigation configuration, compiles and runs the ESP32
firmware logic natively, and runs 133 Python tests.

**Run it before every commit.** If it passes, you have not broken anything
structural.

### 3.3 Run the web application

Two terminals.

```bash
# Terminal 1 — the API
cd backend
../.venv/bin/python seed.py          # once: creates RB001, the lab map, 5 destinations
../.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

```bash
# Terminal 2 — the website
cd frontend
npm install                          # once
npm run dev
```

Open **http://localhost:3000**. API docs at **http://localhost:8000/docs**.

Everything works with no ROS running — robots show as offline, and deploying
a mission fails with "not connected to ROS". That is correct behaviour, and
it is what lets you build the UI on a train.

> **On your machine specifically:** something is already using port 3000. Either
> stop it, or run the frontend elsewhere and tell the backend to allow that
> origin:
> ```bash
> # terminal 2
> npm run dev -- --port 3100
> # terminal 1
> CORS_ORIGINS='["http://localhost:3100"]' ../.venv/bin/python -m uvicorn app.main:app --port 8000
> ```
> Skip the `CORS_ORIGINS` part and the browser silently blocks every request.

### 3.4 Run the robot (simulation)

ROS1 does not run on macOS, so it lives in Docker.

```bash
# once: install Docker Desktop, then
docker compose up -d ros
```

The first build takes 10–20 minutes — it is downloading a full ROS desktop.
Then:

```bash
open http://localhost:6080          # Gazebo and RViz, in your browser
docker compose exec ros bash
```

Inside the container:

```bash
cd /root/rosfleet_ws
catkin_make                          # once, and after adding new files
source devel/setup.bash
roslaunch robot_bringup sim.launch
```

Gazebo opens with the robot in the lab, RViz shows the map and laser. Send it
somewhere three ways:

1. **RViz** — click *2D Nav Goal*, drag on the map
2. **Command line**
   ```bash
   rosservice call /start_mission "{mission_id: 1, destination_name: 'AI Lab',
     goal_x: 3.8, goal_y: 3.4, goal_yaw: 1.57, preempt: false}"
   ```
3. **The website** — once the backend is connected (below)

> ⚠️ **Not yet verified.** The Docker image has never been built on this
> machine — Docker is not installed here. Expect to fix a thing or two on the
> first run; that is normal, and `docs/PROGRESS.md` tracks it as the top open
> risk.

### 3.5 Connect the website to the robot

With `sim.launch` running (it starts rosbridge on port 9090), restart the
backend with ROS enabled — that is the default:

```bash
cd backend
../.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

The header pill turns **ROS CONNECTED**. Now clicking **Deploy** on the
website moves the robot in Gazebo. That is the whole system working.

### 3.6 Run the real robot

```bash
roslaunch robot_bringup real.launch transport:=serial
```

Work through [HARDWARE_INTEGRATION.md](HARDWARE_INTEGRATION.md) first, from
Step 1, in order. Do not skip the wheel-direction and encoder-sign checks.

---

## 4. Feature list

### The robot

- **Autonomous point-to-point navigation** with obstacle avoidance
- **Localisation** on a known map (AMCL particle filter)
- **Mapping** of a new building (gmapping SLAM)
- **Recovery behaviours** — clears costmaps, rotates, retries, then fails cleanly
- **Two independent watchdogs** — the firmware stops the motors after 500 ms
  without a command; the bridge commands a stop after 500 ms without
  `/cmd_vel`
- **Velocity clamping on both sides** — host against a bad planner, firmware
  against a corrupted packet
- **Per-wheel velocity PID** with feedforward and anti-windup
- **Live PID tuning** over the wire (`CFG,kp,0.8`) with no reflash
- **Simultaneous USB and Wi-Fi** — debug over serial while ROS drives over Wi-Fi
- **Battery monitoring** with a low-battery warning
- **Auto-reconnect** when the link drops

### The simulation

- Full physics model with correct mass and inertia
- 10 × 8 m lab world with partitions and furniture
- Simulated RPLiDAR (360°, 10 Hz, with noise)
- **Simulated encoder drift** — so odometry lies the way real odometry lies
- A **loopback mode** that runs the entire real-robot pipeline with no board
  attached

### The web application

- **Dashboard** — fleet status, active missions with live progress, recent history
- **Robots** — register robots; per-robot telemetry, position, battery,
  firmware, mission history, and a stop button
- **Maps** — upload a `.pgm`/`.yaml` from `map_saver`; **click the floor plan
  to place a named destination** instead of typing coordinates
- **Missions** — deploy by picking a robot and a destination; live progress;
  cancel; a timestamped log per mission
- **Analytics** — success rate, average duration, total distance, per-robot
  utilisation, failures bucketed by cause, busiest destinations
- **Live updates** over WebSocket with polling underneath as a safety net
- **ROS connection indicator** in the header, so "everything is offline" is
  never mistaken for "the robot is broken"
- **Graceful degradation** — every page renders with the backend down, the
  robot off, or ROS disconnected

### The engineering

- **133 Python tests, 46 native firmware checks, 7 structural validators**,
  all running on macOS in about three seconds with no ROS and no robot
- **Cross-layer consistency checking** — the build fails if the URDF,
  `hardware.yaml` and the firmware's `config.h` ever disagree about the robot's
  dimensions
- **Static launch-file validation** — catches `$(find ...)` typos in a second
  instead of ten seconds into a Gazebo start
- **Destination reachability checking** — catches a goal placed inside a wall
  before you ever run
- **Mutation-tested** — the critical guards were verified by deliberately
  breaking them and confirming a test failed

---

## 5. Things you should know

The things that will cost you an afternoon if you do not know them.

### 5.1 ROS1 does not run on macOS

Not "is awkward on" — does not run. It lives in Docker, with a browser-based
desktop at `localhost:6080`. Your Mac is the editor; the container is the
robot's computer. The `ros_ws` folder is shared into it live, so editing in
your editor changes it inside the container instantly.

### 5.2 The single most common first-mission failure is the initial pose

On a real robot, **you must tell AMCL where the robot is** before it can
navigate — RViz's *2D Pose Estimate* tool, clicking the spot and dragging in
the direction it faces.

A robot that thinks it is somewhere else will drive confidently into a wall.
It is not a bug and no configuration change fixes it.

### 5.3 Your robot's dimensions live in three files

| File | Used by |
|---|---|
| `robot_description/urdf/common_properties.xacro` | Gazebo, RViz, TF |
| `robot_hardware/config/hardware.yaml` | odometry on the host |
| `firmware/esp32_robot/src/config.h` | the ESP32 |

If they disagree, the robot turns the wrong amount, AMCL keeps losing its
pose, and **it looks exactly like a navigation bug**. People lose days to
this. Hence:

```bash
python3 scripts/check_geometry_sync.py
```

which fails the build if they drift apart. Run it after any measurement change.

### 5.4 Odometry always lies, eventually

Wheels slip. That is not a defect to fix; it is why AMCL exists. Odometry is
excellent over seconds and worthless over minutes.

What *is* worth fixing is a **systematic** error — if the robot reports 2.08 m
after driving 2.00 m, your wheel radius is 4% wrong and every mission inherits
it. Step 9 of the hardware guide is the calibration, and it is the single most
valuable hour you will spend on the physical robot.

### 5.5 Navigation genuinely needs a LiDAR

An ultrasonic sensor gives you one distance. Localisation needs a few hundred
per revolution. There is no clever software substitute.

If the ₹7–9k is not available, that is a legitimate constraint — run
navigation in simulation for the demo and the real robot in teleop plus
odometry, and say so plainly. The architecture is what is being assessed.

### 5.6 Keep the ESP32 dumb

It converts velocity to wheel speeds, runs a PID, counts ticks, reads the
battery. That is all. No maps, no planning, no mission logic, no Wi-Fi
dashboard.

The reason is diagnostic: any misbehaviour is then either *"the wheels ignored
the command"* (firmware) or *"the wrong command was sent"* (ROS) — never a
tangle of both.

### 5.7 One command halves any debugging problem

```bash
rostopic echo /cmd_vel
```

- **Nothing published** → the problem is above: move_base, the goal, the map,
  AMCL not localised.
- **Published but the robot does not move** → the problem is below: the
  bridge, the link, the firmware, the wiring, the battery.

### 5.8 Campus Wi-Fi will probably block the robot

Many college networks use client isolation, which stops your Mac reaching the
ESP32 even though both show as connected. Symptom: `PING` never answers.
Carry a phone hotspot or a cheap travel router and put both on that.

### 5.9 Two traps specific to this codebase

**Tailwind v4 class names.** Colours are declared in `@theme` and become real
utilities: `bg-panel`, `text-ink-dim`. The v3 bracket form `bg-[--color-panel]`
**compiles to nothing, silently** — the build passes, the typecheck passes,
and the page just looks wrong. This bit once already; see PROGRESS.md.

**CORS.** The backend allows `localhost:3000` by default. Run the frontend
anywhere else without setting `CORS_ORIGINS` and every request is blocked by
the browser, which `fetch` reports identically to "the backend is down".

### 5.10 Never run a lithium pack flat

Below its empty voltage a Li-ion cell is permanently damaged and can become
unsafe. The low-battery warning exists for a reason. Never charge unattended.

---

## 6. How to work on it

### Where things live

```
ros_ws/src/
  robot_description/   what the robot physically is (URDF)
  robot_gazebo/        the simulated world
  robot_hardware/      the ONLY code that knows an ESP32 exists
  robot_navigation/    move_base, AMCL, gmapping, costmaps
  mission_manager/     "go to the AI Lab" → navigation goals
  robot_bringup/       top-level launch files

firmware/esp32_robot/  PWM, encoders, PID, protocol
backend/               FastAPI + database + ROS bridge
frontend/              Next.js dashboard
scripts/               validators and the test runner
docs/                  these four documents
```

### The loop to work in

```
edit  →  ./scripts/run_tests.sh  →  run it  →  commit
```

Commit when something **works**, not when you stop typing. Every commit
message in this repository says what was verified and how; keep that up — it
is what makes the history useful when something breaks in three weeks.

### Adding a destination

Easiest: the **Maps** page, click the spot, name it. That is the feature.

For ROS-only testing, `mission_manager/config/destinations.yaml` holds a copy,
and `seed.py` loads it into the database. To read a real pose off the robot:

```bash
rosrun tf tf_echo map base_footprint
```

Then check it is somewhere the robot can actually stand:

```bash
python3 scripts/check_destinations.py
```

### Changing the robot's size

1. Measure it.
2. Edit all three files from §5.3.
3. `python3 scripts/check_geometry_sync.py`
4. `python3 scripts/validate_urdf.py`
5. Reflash the ESP32.

### Debugging, in order of usefulness

```bash
rostopic echo /cmd_vel            # is anything commanding motion?
rostopic hz /scan /odom           # are the sensors alive, at the right rate?
rosrun tf view_frames             # is the transform tree intact?
rosrun rqt_graph rqt_graph        # who is actually talking to whom?
rostopic echo /robot_telemetry    # battery, link latency, firmware, errors
```

And with no ROS at all, talking straight to the board:

```bash
python3 ros_ws/src/robot_hardware/scripts/esp32_console.py --serial /dev/ttyUSB0
```

This is the one that answers *"is it the firmware or is it ROS?"* — the first
question worth asking.

---

## 7. What to improve, in priority order

Ordered by value for effort. **Do the first three before anything else** —
they are what turn a very good repository into a working robot.

### Tier 0 — Finish what is started

| # | Task | Why | Effort |
|---|---|---|---|
| 1 | **Install Docker, build the image, run `sim.launch`** | Nothing else can be validated until this works. It is the single biggest open risk | half a day |
| 2 | **Connect the backend to the running ROS** and deploy a mission from the website | The first moment the whole stack is proven together. This is your demo | an hour |
| 3 | **Flash the firmware with PlatformIO** | The logic is tested; it has never been compiled for the board. Expect small fixes | an hour |

### Tier 1 — High value, genuinely achievable

| # | Feature | Why it is worth it |
|---|---|---|
| 4 | **Multi-stop missions** (a route, not a single goal) | "Collect from Reception, deliver to AI Lab" is a *product*, not a demo. The mission state machine already has the structure; it needs a waypoint list |
| 5 | **Return-to-charge on low battery** | Autonomy that handles its own limits reads as real engineering. You already have battery telemetry and a Reception/home destination |
| 6 | **Mission queue** | Right now a busy robot refuses new missions. Queuing them is a small change to `mission_service` and makes the fleet usable by more than one person |
| 7 | **SLAM from the website** | A "Map this floor" button that runs gmapping and saves the result closes the last loop where you have to drop to the command line |
| 8 | **Web teleop** (drive with arrow keys from the browser) | Genuinely useful for recovery when the robot gets stuck, and it demos instantly |

### Tier 2 — Strong additions once Tier 1 works

| # | Feature | Notes |
|---|---|---|
| 9 | **Digital twin** — live 3D view of the robot on the website | You mentioned wanting this. Mirror the pose into a simple three.js scene. High visual impact, moderate effort |
| 10 | **Camera stream** | An ESP32-CAM or a phone. Lets an operator see what the robot sees |
| 11 | **Multiple robots** | The database already supports it; ROS needs per-robot namespacing. Significant work — do not start it until one robot is solid |
| 12 | **Authentication and roles** | Operator vs viewer. Needed if anyone else will use it |
| 13 | **Scheduled missions** | "Every day at 09:00, patrol the corridor" |

### Tier 3 — Engineering quality

| # | Task | Why |
|---|---|---|
| 14 | **CI** (GitHub Actions running `./scripts/run_tests.sh`) | The suite already exists; wiring it up takes twenty minutes and protects the repo |
| 15 | **Alembic migrations** | `create_all()` is fine now, but the day you change a column with real data in the table, you will want them |
| 16 | **`rosbag` recording of failed missions** | Replay exactly what the robot saw when it failed. This is how real robotics teams debug |
| 17 | **A settings page** | Move the tunables (speed limits, battery thresholds) out of YAML and into the UI |

### Deliberately not recommended yet

Kubernetes, microservices, Redis, cloud deployment, reinforcement learning,
computer-vision obstacle classification, a mobile app. Each adds a lot of
surface area and nothing to the thing being assessed. Revisit if the core is
finished and you have time spare.

---

## 8. Presenting it

The strongest thing about this project is not the robot. It is that
**simulation and hardware are interchangeable**, and you can prove it in
thirty seconds by opening the two bringup launch files side by side: the
navigation, mission and bridge includes are identical, and only the bottom
layer swaps between Gazebo and the real chassis.

A demo order that works:

1. **Start in simulation.** Deploy a mission from the website. The robot
   plans, drives, arrives; the progress bar fills. Everything visible at once.
2. **Put an obstacle in its path** in Gazebo. It replans around it. The
   mission log records `REPLANNED`.
3. **Show the analytics page.** Success rates, failure causes. This is a
   product, not a script.
4. **Then show the architecture diagram** and explain that the same stack
   drives the physical robot, with the ESP32 in place of Gazebo.
5. **Show the test suite** running in three seconds, and the geometry checker
   catching a deliberately broken measurement. Very few student projects can
   do this, and it demonstrates engineering judgement rather than just effort.

If the hardware is not finished by then, say exactly that, and show what is:
firmware logic tested natively, the protocol working over the loopback
transport, and the bringup guide you wrote for the day the parts arrive.
Honest scope is more impressive than a robot that mysteriously does not work
during the demo.

---

## 9. Quick reference

### Commands

```bash
# checks (no ROS, 2 seconds)
./scripts/run_tests.sh
python3 scripts/check_geometry_sync.py      # do the 3 config files agree?
python3 scripts/check_nav_config.py         # is navigation self-consistent?
python3 scripts/check_destinations.py       # can the robot reach every goal?
python3 scripts/check_bringup_parity.py     # are sim and real still interchangeable?
python3 scripts/validate_urdf.py            # is the robot model valid?
python3 scripts/generate_sim_map.py         # rebuild the simulated map

# web application
cd backend && ../.venv/bin/python seed.py
cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev

# ROS (inside the container)
roslaunch robot_bringup sim.launch                    # everything, simulated
roslaunch robot_bringup real.launch transport:=serial # everything, real
roslaunch robot_navigation mapping.launch             # build a map
roslaunch robot_gazebo teleop.launch                  # drive by keyboard
rosrun map_server map_saver -f ~/floor1               # save the map

# firmware
cd firmware/esp32_robot && pio run -t upload
pio device monitor -b 115200
```

### Ports

| Port | What |
|---|---|
| 3000 | website (**already in use on your machine** — see §3.3) |
| 8000 | backend API, docs at `/docs` |
| 6080 | Gazebo + RViz desktop in the browser |
| 9090 | rosbridge, how the backend reaches ROS |
| 11311 | ROS master |
| 5432 | PostgreSQL |

### The protocol, for when you have a serial monitor open

```
you type          the board replies
────────          ─────────────────
CMD,0.1,0         ENC,15204,15198,48320     cumulative ticks + its own clock
CMD,0,0.5         BAT,7.82                  volts
CMD,0,0           DIST,42.0                 cm, optional bumper sensor
PING,1            PONG,1
RST               LOG,encoders reset        zero the tick counters
CFG,kp,0.8        LOG,gains kp=0.800 …      live PID tuning, no reflash
```

### When something is wrong

| Symptom | Look at |
|---|---|
| Robot does not move | `rostopic echo /cmd_vel` — above or below? (§5.7) |
| Drives in a curve when told to go straight | wheel PID, or `ticks_per_rev` differing per motor |
| Turns roughly twice too far | `wheel_separation` — measure contact points, not the chassis |
| "No path" with nothing in the way | `check_nav_config.py`, then the initial pose |
| AMCL keeps losing the robot | recalibrate odometry (hardware guide, Step 9) |
| Website shows everything offline | the header pill — is it the backend, or ROS? |
| Every request fails in the browser | CORS (§5.9) |
| Colours look wrong after a UI edit | Tailwind v4 class names (§5.9) |
