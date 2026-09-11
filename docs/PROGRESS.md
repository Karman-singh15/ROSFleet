# Implementation Log

The running record of what has been built, what was decided and why, and what
comes next. **Every completed piece of work gets an entry here.**

- **Started:** 11 September 2026
- **Target hardware:** ESP32 + 2-wheel differential drive chassis + RPLiDAR A1
- **Development machine:** MacBook, Apple M4, 16 GB, macOS 15
- **ROS distribution:** ROS1 Noetic, inside Docker (ROS1 does not run natively
  on macOS)

---

## Status at a glance

| # | Phase | State | Notes |
|---|---|---|---|
| 1 | Project skeleton and tooling | ✅ Done | test harness runs on macOS with no ROS |
| 2 | Robot model (URDF) | ✅ Done | validated: geometry, mass, kinematic tree |
| 3 | Gazebo simulation | ✅ Done | lab world + ground-truth map generated |
| 4 | Hardware abstraction layer | ✅ Done | 37 tests, mutation-checked |
| 5 | ESP32 firmware | ✅ Done | 46 native checks; not yet run on a board |
| 6 | Navigation stack | ✅ Done | configs written and cross-validated |
| 7 | Mission manager | ✅ Done | 27 tests incl. the cancel/arrive race |
| 8 | Docker environment | ⚠️ Written, unverified | Docker not installed on this machine |
| 9 | Backend (FastAPI + PostgreSQL) | ✅ Done | 55 tests + live uvicorn smoke test |
| 10 | Frontend (Next.js) | ✅ Done | builds clean; driven through a real browser |
| 11 | Analytics | ✅ Done | success rate, utilisation, failure causes |
| 11b | Digital twin (live 3D) | ⬜ Not started | optional stretch goal |
| 12 | Physical robot bringup | ⬜ Blocked | waiting on parts |

**Verification status:** everything marked ✅ has automated checks that run on
macOS via `./scripts/run_tests.sh` — **132 Python tests, 46 native firmware
checks and 6 structural validators**, in about three seconds. The backend and
website have additionally been run together and driven through a real
browser. Nothing has yet been executed inside a ROS master or on physical
hardware — that is the honest state of the project, and both gaps are tracked
below as open risks.

---

## How to use this document

- **Log entries** are appended as work completes, newest at the bottom of each
  phase. Each records what was built, how it was verified, and anything
  surprising.
- **Decisions** records choices that were not obvious, with the reasoning, so
  neither of us re-litigates them in three weeks.
- **Open risks** is the honest list of what could still go wrong.
- **Next up** is the running to-do list.

---

## Log

### 2026-09-11 — Phase 1: project skeleton and macOS test harness

**Built**

- Repository layout: `ros_ws/`, `firmware/`, `backend/`, `frontend/`,
  `docker/`, `docs/`, `scripts/`, `maps/`.
- `scripts/setup_dev.sh` — creates `.venv` with `xacro`, `urdf-parser-py`,
  `pytest`, `pyserial`, `pyyaml`.
- `scripts/run_tests.sh` — the single gate to pass before any commit.

**Why this came first.** ROS1 cannot be installed on macOS, so without a
laptop-side test harness every trivial mistake would cost a Docker round
trip. Seven independent checks now run in about two seconds.

**Verified** — `./scripts/run_tests.sh` passes from a clean checkout after
`./scripts/setup_dev.sh`.

---

### 2026-09-11 — Phase 2 & 3: robot model and simulation

**Commit** `29c07ce` *Add robot URDF model and Gazebo simulation world*

**Built**

- `robot_description` — xacro model: chassis, two driven wheels, caster,
  LiDAR. Every dimension is a named constant in `common_properties.xacro`.
- `robot.gazebo.xacro` — `diff_drive` and `laser` plugins, publishing the
  same `/cmd_vel`, `/odom`, `/scan` contract the real hardware will.
- `robot_gazebo` — 10 × 8 m lab world with partitions and furniture.
- `scripts/validate_urdf.py` — expands and structurally checks the model with
  no ROS installed.

**Verified**

- xacro expands; result parses as valid URDF.
- All 6 required links and both drive joints exist.
- Exactly one kinematic root (`base_footprint`), no orphan links.
- Every link with collision geometry has non-zero mass and inertia.
- Wheel contact points and the caster land **exactly** on z = 0 (computed:
  wheel centre 0.0325 m = wheel radius; caster centre 0.0160 m = caster
  radius).

**Notes**

- Modelled as 2 driven wheels + caster rather than 4-wheel skid steer.
  Skid steer needs four encoders and has odometry that is wrong by design
  during turns. If the chassis has four motors, drive them in pairs and
  treat it as differential.
- An XML validator caught `------` inside an XML comment, which is illegal
  and would have failed at ROS launch time. `--` runs inside comments are now
  checked by `run_tests.sh`.

---

### 2026-09-11 — Phase 4: hardware abstraction layer

**Commit** `7d59f51` *Add hardware abstraction layer between ROS and the ESP32*

**Built**

- `esp32_link.py` — line-framed ASCII transport over serial, Wi-Fi TCP, or an
  in-process **loopback** ESP32.
- `odometry.py` — differential-drive dead reckoning, exact arc integration,
  wraparound-safe tick deltas.
- `hardware_bridge.py` — the only node that knows an ESP32 exists.
- `esp32_console.py` — hand-drive the board with no ROS running.
- `fake_telemetry.py` — keeps `/robot_telemetry` populated in simulation.

**Verified** — 37 tests, run against the real node file using a stub ROS
(`test/ros_stubs.py`) so it is testable on macOS. Covers: straight-line and
rotational odometry against closed-form geometry, encoder wraparound,
duplicate and absurd timestamps, deadman stop, covariance shape, quaternion
normalisation, malformed and truncated input, TCP line reassembly.

**Mutation-checked.** Three deliberate bugs were injected to prove the tests
have teeth; each was caught:

| Injected bug | Caught by |
|---|---|
| deadman never fires on a stale command | `test_stale_cmd_vel_triggers_a_stop` |
| angular sign convention flipped | 6 tests |
| exact arc replaced by straight-line approximation | `test_arc_uses_exact_integration...` |

**Notes**

- The `loopback` transport turned out to be the most valuable piece here: the
  complete real-robot pipeline runs with no board attached.
- Encoder messages carry **cumulative** counts, not deltas, so a dropped line
  self-heals instead of corrupting odometry permanently.
- The ESP32 timestamps its own messages, so Wi-Fi jitter cannot distort the
  velocity estimate.

---

### 2026-09-11 — Phase 5: ESP32 firmware

**Commit** `e2dc2c1` *Add ESP32 firmware and cross-layer geometry guard*

**Built**

- `config.h` — all pins and drivetrain constants in one place.
- `Motor.h` — 20 kHz LEDC PWM (above hearing), stiction deadband, coast stop.
- `Encoder.h` — quadrature decoding with ISR-safe critical sections.
- `PidController.h` — velocity PID with feedforward and integral anti-windup.
- `Kinematics.h`, `Protocol.h` — hardware-free, so the risky logic is testable
  on a laptop.
- `main.cpp` — control loop, watchdog, telemetry, serial **and** Wi-Fi
  simultaneously.
- `scripts/check_geometry_sync.py` — fails if URDF, `hardware.yaml` and
  `config.h` disagree.

**Verified** — 46 native checks compiled with `-Wall -Wextra -Werror` and run
on the Mac. Covers truncated and non-numeric commands being *rejected* rather
than half-applied, turn-ratio-preserving saturation, anti-windup recovery
after a stall, zero-`dt` safety, and a full command → ticks → recovered
velocity round trip. Geometry checker confirmed to fail on an injected
mismatch.

**⚠️ Not verified** — never compiled by PlatformIO, never flashed. Expect to
fix small things on first upload.

**Notes**

- **A pin conflict was caught during review**: GPIO39 was assigned to both the
  right encoder B channel and the battery ADC. Encoders moved to
  GPIO16/17/4/23 — which also fixes a subtler problem, since GPIO34–39 are
  input-only with **no internal pull-ups**, and most hall encoders need one.
- Wheel-speed saturation **scales both wheels together** rather than clipping
  each. Independent clipping changes the commanded curvature, so a robot
  asked to drive fast round a tight arc would go straighter than commanded —
  into the obstacle it was curving around.
- `platform = espressif32@6.5.0` is pinned deliberately: Arduino-ESP32 3.x
  renamed the LEDC PWM API and an automatic upgrade would silently break
  motor control.

---

### 2026-09-11 — Phase 6: navigation stack

**Commit** `cfeb2f3` *Add autonomous navigation stack with config validation*

**Built**

- Costmaps (common / global / local), DWA local planner, move_base, AMCL and
  gmapping configuration — all sized for a 20 cm robot rather than the
  TurtleBot-scale defaults most tutorials carry.
- `navigation.launch`, `mapping.launch`, `navigation.rviz`.
- `scripts/generate_sim_map.py` — derives a ground-truth occupancy grid from
  the Gazebo world.
- `scripts/check_nav_config.py` — cross-validates the navigation configuration.

**Verified**

- Generated map renders to exactly the `lab.world` geometry (checked by ASCII
  render); the robot spawn point lands in free space.
- All YAML parses; navigation validator passes.
- Validator confirmed to catch three injected faults: a planner faster than
  the drivetrain, an inflation radius that seals a 0.75 m doorway, and a DWA
  lookahead overrunning the local costmap.

**Notes**

- Generating the map from the world means navigation is testable on day one,
  before ever running SLAM. The real robot's map still comes from
  gmapping + map_saver.
- `odom_alpha` values are raised above ROS defaults because cheap plastic
  gearboxes slip far more than the defaults assume.
- Default inflation `0.22 m` against a circumscribed robot radius of
  `0.142 m` leaves 0.31 m of clearance in a 0.75 m doorway.

---

### 2026-09-11 — Phase 7: mission manager and bringup

**Commit** `1ef3528` *Add mission manager and one-command system bringup*

**Built**

- `state.py` — ROS-free mission state machine.
- `mission_manager_node.py` — move_base actionlib client, latched
  `/mission_status` at 2 Hz, `/mission_events` log stream, goal timeout,
  mid-mission hardware-loss abort.
- `StartMission` / `CancelMission` services; `MissionStatus` / `MissionEvent`
  messages.
- `robot_bringup` — `sim.launch` and `real.launch`.
- `scripts/check_launch_refs.py`, `scripts/check_destinations.py`.

**Verified** — 27 tests. The ones that matter most:

- A cancel arriving *after* arrival cannot overwrite `SUCCEEDED`.
- Progress does not rewind when a replan is longer than the original path.
- An AMCL relocalisation jump is not counted as distance travelled.
- Distance resets per mission.
- The event buffer is bounded.

Launch validator confirmed to catch an injected path typo. The destination
checker found the **"AI Lab" destination placed inside a table** at
(3.2, 2.6); moved to (3.8, 3.4) after verifying clearance.

**Notes**

- `sim.launch` and `real.launch` differ by exactly one include. That
  difference is the payoff for the whole architecture.
- Mission state lives in ROS, not the backend, so the robot finishes safely
  even if the API process dies mid-mission.

---

### 2026-09-11 — Phase 8: Docker environment

**Built**

- `docker/Dockerfile` — ROS Noetic desktop-full + navigation stack +
  rosbridge + noVNC desktop, native arm64.
- `docker-compose.yml` — `ros` and `db` services, bind-mounted workspace,
  named volumes for build output.
- `docker/entrypoint.sh`, `docker/supervisord.conf`.

**⚠️ Not verified.** Docker is not installed on this machine. Compose YAML,
shell syntax and supervisord config all parse, but the image has never been
built and the container has never run. **This is the first thing to test.**

**Notes**

- Software rendering (`LIBGL_ALWAYS_SOFTWARE=1`) is forced because Apple
  Silicon has no GPU passthrough to Linux containers. Gazebo will be slower
  than native but usable.
- `shm_size: 2gb` — Gazebo's physics uses shared memory and crashes on
  Docker's 64 MB default.
- Build output goes in named volumes, not the bind mount: catkin writes
  thousands of small files and doing that across a macOS bind mount is
  painfully slow.

---

### 2026-09-11 — Phase 9: backend

**Commit** `e45d9e7` *Add FastAPI backend with mission, map and analytics APIs*

**Built**

- SQLAlchemy models: robots, maps, destinations, missions, mission events,
  telemetry.
- `mission_service` — resolves a destination name to a pose, writes the row,
  calls ROS with the row id so both sides share one mission identifier.
- `ros_client` — one interface, three implementations: `RosBridgeClient`
  (real), `NullRosClient` (no ROS running), `FakeRosClient` (tests).
- `ros_sync` — ROS topics into the database and out to browsers.
- `map_service` — parses the `.yaml` and `.pgm` header directly.
- `analytics_service` — computed on demand, no pre-aggregation.
- 21 REST endpoints plus a `/ws` WebSocket; `backend/seed.py`.

**Verified** — 55 tests. Additionally run for real under uvicorn and driven
with `curl`: health, robot creation, a mission correctly refused with
"not connected to ROS", analytics, and the OpenAPI docs all responded.

**Mutation-checked.** Three injected bugs were caught:

| Injected bug | Caught by |
|---|---|
| terminal-state guard removed (a late ROS message rewrites a finished mission) | `test_a_late_message_cannot_resurrect_a_finished_mission` |
| success rate counts in-flight missions in the denominator | `test_success_rate_excludes_in_flight_missions` |
| a ROS-refused mission left `QUEUED` instead of `FAILED` | `test_a_mission_ros_refuses_is_failed_not_left_queued` |

**A fourth mutation initially passed, which was itself the finding.** The
NaN-battery test round-tripped through SQLite, and **SQLite silently coerces
NaN to NULL** — so the test passed with the guard removed, and the bug would
only have appeared in production against PostgreSQL, where NaN survives and
`json.dumps` emits the bare token `NaN`, which is not valid JSON and breaks
the dashboard's fetch. The guard was extracted to
`robot_service.clean_float()` and the test now targets it directly; the
mutation is now caught.

**Notes**

- A mission **copies** its destination's name and pose at creation rather
  than only referencing them. Destinations get renamed and deleted; finished
  history must keep meaning regardless.
- Cancelling succeeds even when ROS is unreachable. A mission left running in
  the database for a robot that is gone is worse than a cancel ROS never
  heard — the robot's own watchdogs stop it either way.
- The backend starts with or without ROS. A missing robot is a normal state,
  not a startup failure, so the dashboard loads and shows everything offline.
- `seed.py` is idempotent and re-syncs destinations from the ROS config,
  verified by corrupting a row and re-running.

---

### 2026-09-11 — Phase 10: frontend

**Commit** `50638fd` *Add the Next.js dashboard and serve maps as PNG*

**Built**

- Next.js 15 App Router + TypeScript + Tailwind v4, seven routes: dashboard,
  robots, robot detail, maps, missions, mission detail, analytics.
- `MapView` — click the floor plan to place a named destination.
- `useLive` — WebSocket updates merged into existing rows, polling beneath.
- `pgm_to_png` (backend) — browsers cannot render PGM, so `/api/maps/{id}/image`
  converts on the fly; a minimal encoder rather than a Pillow dependency.

**Verified** — typecheck and production build clean. Backend and frontend run
together and driven through a real browser: every page renders, the map image
and all five seeded destinations appear in the right places, click-to-place
created a destination end to end, and the console is free of application
errors. 13 new backend tests decode the generated PNG with a real decoder and
compare every pixel, rather than only checking the header.

**Two real bugs were found this way, both invisible to the build.**

1. **Every Tailwind colour class was compiling to nothing.** The code used
   `bg-[--color-panel]`, which is Tailwind v3 syntax; v4 generates utilities
   from `@theme` instead, so the correct form is `bg-panel`. The build
   succeeded, the typecheck passed, and the page still *looked* roughly right
   because `globals.css` sets the body colours directly — only a screenshot
   showed the destination labels missing their background chips. Confirmed by
   grepping the compiled CSS: none of the 164 class names existed. Fixed
   across 11 files.

2. **A 5 px offset between where the map was clicked and where the marker
   appeared.** Checked numerically against the map metadata instead of by
   eye, which traced it to the screenshot tooling (browser viewport 1470 px,
   capture 1456 px, a 1.0096 scale) rather than to the application. The
   coordinate conversion is exact. Worth recording precisely because "it
   looks about right" would have left a real doubt.

Also found: the frontend reported "Cannot reach the backend" when the real
cause was a CORS rejection. `fetch` rejects identically for both and the
browser deliberately hides which, so the message now names both causes.

**Notes**

- The frontend contains no ROS concepts at all — no `roslibpy`, no
  `/cmd_vel`, no topic names. `src/lib/api.ts` is the only file that touches
  the network.
- Live updates are merged into existing rows rather than triggering a
  refetch, so numbers move the instant the robot does.

---

## Decisions

Choices that were not obvious, recorded so they do not get re-argued.

| # | Decision | Why | Alternative rejected |
|---|---|---|---|
| 1 | Define the robot as a **topic contract** (`/cmd_vel`, `/odom`, `/scan`, `/tf`) | Lets simulation and hardware be swapped with a one-line change | Writing hardware-specific navigation |
| 2 | ROS1 Noetic, not ROS2 | The tutorials, the packages and the answers you will find all assume ROS1; ROS2 would cost weeks | ROS2 Humble |
| 3 | ROS in **Docker** on macOS | ROS1 does not run natively on macOS | A Linux VM (slower); dual-booting (disruptive) |
| 4 | ESP32 stays **dumb** | Any misbehaviour is either "wheels ignored the command" or "wrong command sent", never both | Running navigation on the ESP32 |
| 5 | Plain **ASCII** protocol | Debuggable with a serial monitor or `nc`; saves nothing useful to make it binary | Binary framing, protobuf |
| 6 | **Cumulative** encoder counts | A dropped line self-heals; deltas corrupt odometry forever | Sending tick deltas |
| 7 | ESP32 timestamps its own messages | Wi-Fi jitter cannot distort velocity | Timestamping on the host |
| 8 | **Two** watchdogs (firmware + bridge) | Either alone is a robot that drives into a wall when the other fails | One watchdog |
| 9 | Hardware-free `Kinematics.h` / `Protocol.h` | The riskiest logic is testable on a laptop instead of on a moving robot | Testing only on hardware |
| 10 | Frontend talks **only** to the backend | ROS internals can change without touching React; the site still renders with the robot off | `roslibjs` in the browser |
| 11 | Mission state lives in **ROS** | The robot finishes safely if the backend crashes | Backend drives move_base directly |
| 12 | Generate the sim map from the world | Navigation is testable before SLAM works | Requiring gmapping first |
| 13 | Cross-layer **consistency checkers** | Geometry appears in 3 files; a mismatch looks like a navigation bug and is nearly unfindable from the ROS side | Trusting discipline |
| 14 | Pin `espressif32@6.5.0` | Arduino-ESP32 3.x renamed the LEDC API; an auto-upgrade would break motor control silently | Floating the platform version |
| 15 | Exact arc odometry integration | The straight-line approximation drifts noticeably on tight indoor turns | The common simplified form |
| 16 | Backend owns names, ROS owns poses | ROS never needs a database; the website never needs coordinates | Storing destinations in ROS params |
| 17 | Missions copy their destination's pose | A renamed or deleted destination must not rewrite finished history | Referencing the destination only |
| 18 | Analytics computed on demand | At this scale the query is instant; a stale cache that disagrees with the mission list confuses users far more | Pre-aggregated summary tables |
| 19 | `NullRosClient` / `FakeRosClient` behind one interface | The entire backend and frontend are developable with no ROS and no robot | Mocking roslibpy per test |
| 20 | Convert maps to PNG on request, not at upload | A map regenerated on disk is served fresh with no re-upload | Converting once at upload time |
| 21 | WebSocket **and** polling on every live page | A dashboard that silently freezes when a socket drops is worse than one three seconds stale | WebSocket alone |
| 22 | Show the backend's error text verbatim in the UI | "robot is already running mission 12" is actionable; "something went wrong" is not | Generic error toasts |

---

## Open risks

| Risk | Impact | Mitigation / status |
|---|---|---|
| **Nothing has run in real ROS yet** | Unknown integration issues | Docker build is the next task |
| **Firmware never compiled by PlatformIO** | Small errors likely on first flash | Logic is tested natively; expect an hour of fixes |
| Backend/frontend never run against real ROS | The rosbridge message shapes are assumed, not observed | `FakeRosClient` uses the documented shapes; verify on first connection |
| Gazebo performance under software rendering on M4 | Slow simulation | Headless (`gui:=false`) + RViz only if needed |
| LiDAR budget (₹7–9k) | No LiDAR means no real autonomous navigation | Documented fallback: sim for navigation, real robot in teleop |
| Campus Wi-Fi client isolation | ESP32 unreachable over Wi-Fi | Documented: phone hotspot or travel router |
| Cheap gearmotor mismatch | Robot curves when told to go straight | Per-wheel PID; documented in troubleshooting |
| Odometry drift on smooth floors | Poor localisation | Step 9 calibration; raised `odom_alpha` values |

---

## Next up

In order.

1. **Install Docker Desktop and build the image.** Until this works, nothing
   else can be validated for real.
2. **Run `sim.launch` end to end.** Gazebo starts, the robot spawns, RViz
   shows the map, a 2D Nav Goal makes it drive.
3. **Fix whatever that reveals.** First contact with a real ROS master always
   finds something.
4. **Connect the backend to the running ROS.** `docker compose up -d`, then
   `POST /api/missions` and watch the robot move in Gazebo. This is the first
   moment the whole stack is proven together.
5. **Phase 12 — hardware.** Follow `docs/HARDWARE_INTEGRATION.md` from
   Step 1 the day the parts arrive. Steps 1–7 need only the ESP32, the
   motors and a battery; the LiDAR is not needed until Step 10.
6. *(Optional)* **Digital twin.** Mirror the live robot pose into a 3D view
   on the website. Only worth doing once everything above works.

---

## Test inventory

What `./scripts/run_tests.sh` actually checks, and what each protects.

| Check | Count | Protects against |
|---|---|---|
| URDF structural validation | 7 assertions | broken model, floating wheels, zero-mass links |
| XML well-formedness | all launch/xacro/world | typos that fail seconds into a launch |
| Geometry consistency | 5 quantities × 3 files | the robot turning the wrong amount |
| Launch reference resolution | 32 references | `$(find ...)` typos, non-executable nodes |
| Destination reachability | per destination | goals inside walls and furniture |
| Navigation config sanity | 6 cross-checks | planner outrunning the drivetrain, sealed doorways |
| Firmware native checks | 46 | protocol parsing, kinematics, PID guards |
| ROS-side unit tests | 64 | odometry, bridge behaviour, mission state machine |
| Backend API tests | 68 | endpoints, ROS sync, analytics arithmetic, PNG encoding |

**Total: 132 Python tests + 46 native checks + 6 structural validators.**

The frontend is covered by `npm run build` and `npx tsc --noEmit`, plus the
manual browser pass recorded above.

All of it runs on macOS in about three seconds with no ROS and no robot:

```bash
./scripts/run_tests.sh
```
