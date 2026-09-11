# Hardware Integration Guide

How to take the software that already works in simulation and connect it to a
physical robot.

**The premise:** by the time you follow this guide, navigation, missions, the
backend and the website already work against Gazebo. You are not "building
the robot project" here. You are implementing the *physical backend* for an
already-working ROS robot. That is a much smaller job, and this guide is the
whole of it.

---

## Contents

1. [Parts list](#1-parts-list)
2. [How the electronics connect](#2-how-the-electronics-connect)
3. [The golden rule of bringup](#3-the-golden-rule-of-bringup)
4. [Step 1 — Flash the ESP32, no motors attached](#step-1--flash-the-esp32-no-motors-attached)
5. [Step 2 — Motors spin the right way](#step-2--motors-spin-the-right-way)
6. [Step 3 — Encoders count the right way](#step-3--encoders-count-the-right-way)
7. [Step 4 — Measure ticks per revolution](#step-4--measure-ticks-per-revolution)
8. [Step 5 — Measure the wheel geometry](#step-5--measure-the-wheel-geometry)
9. [Step 6 — Calibrate the battery divider](#step-6--calibrate-the-battery-divider)
10. [Step 7 — Calibrate feedforward and tune the PID](#step-7--calibrate-feedforward-and-tune-the-pid)
11. [Step 8 — Connect ROS over USB](#step-8--connect-ros-over-usb)
12. [Step 9 — Verify odometry against a tape measure](#step-9--verify-odometry-against-a-tape-measure)
13. [Step 10 — Add the LiDAR](#step-10--add-the-lidar)
14. [Step 11 — Cut the cable: switch to Wi-Fi](#step-11--cut-the-cable-switch-to-wi-fi)
15. [Step 12 — Map your building](#step-12--map-your-building)
16. [Step 13 — First autonomous mission](#step-13--first-autonomous-mission)
17. [Troubleshooting](#troubleshooting)
18. [Safety](#safety)

---

## 1. Parts list

### Minimum viable robot

| Part | Notes | Approx ₹ |
|---|---|---|
| 4-wheel or 2-wheel + caster chassis | acrylic, with motor mounts | 400–700 |
| 2 × BO/TT gearmotor **with encoder** | the encoder is non-negotiable | 500–900 |
| ESP32 DevKit V1 (WROOM) | avoid WROVER: GPIO16/17 are taken by PSRAM | 350 |
| L298N or TB6612FNG motor driver | TB6612 is smaller, cooler, more efficient | 80–250 |
| 2S Li-ion pack (7.4 V) + holder | or 6×AA as a fallback | 300–600 |
| Buck converter to 5 V | powers the ESP32 from the pack | 60 |
| Resistors 20 kΩ + 10 kΩ | the battery voltage divider | 5 |
| Jumper wires, screws, standoffs | | 150 |

### For real autonomous navigation

| Part | Notes | Approx ₹ |
|---|---|---|
| **RPLiDAR A1M8** | the single most valuable upgrade | 7,000–9,000 |

> **On skipping the LiDAR.** You can build and demonstrate everything else
> without one — teleop, odometry, the dashboard, mission plumbing, the whole
> web application. But AMCL and move_base fundamentally need `/scan`. An
> ultrasonic sensor is *not* a substitute: it gives you one distance, and
> localisation needs a few hundred per revolution. If the budget will not
> stretch, run navigation in simulation for the demo and the real robot in
> teleop + odometry mode. Say so openly in your presentation; it is a
> legitimate engineering trade-off, and the architecture is what is being
> assessed.

### Encoders matter more than you think

A motor "with encoder" usually means a magnetic (hall) encoder on the rear
motor shaft, 11–13 pulses per motor revolution, multiplied by the gearbox
ratio. **Without encoders there is no `/odom`, and without `/odom` there is
no navigation** — no localisation, no path following, nothing. If you have to
choose between a nicer chassis and encoders, buy the encoders.

---

## 2. How the electronics connect

```
                      ┌────────────────────┐
     2S Li-ion 7.4V ──┤ + ──────┬──────────┼── L298N / TB6612  VM
                      │         │          │
                      │    ┌────▼─────┐    │
                      │    │   buck   │    │
                      │    │  to 5 V  │    │
                      │    └────┬─────┘    │
                      │         └──────────┼── ESP32  VIN
                      │                    │
     GND ─────────────┴────────────────────┴── COMMON GROUND  ★
                                                (all three, one node)

   ESP32                          motor driver              motors
   ────────                       ─────────────             ──────
   GPIO26  ─────────────────────> IN1  (left)
   GPIO27  ─────────────────────> IN2  (left)               ┌───────┐
   GPIO14  ─────────────────────> ENA  (left PWM)  ───────> │ LEFT  │
                                                            └───┬───┘
   GPIO25  ─────────────────────> IN3  (right)                  │
   GPIO33  ─────────────────────> IN4  (right)              ┌───▼───┐
   GPIO32  ─────────────────────> ENB  (right PWM) ───────> │ RIGHT │
                                                            └───────┘
   encoders                                   battery sense
   ────────                                   ─────────────
   GPIO16  <── left  encoder A                      7.4 V
   GPIO17  <── left  encoder B                        │
   GPIO4   <── right encoder A                      20 kΩ
   GPIO23  <── right encoder B                        ├──> GPIO34 (ADC)
   3V3     ──> encoder VCC  (check your part!)      10 kΩ
   GND     ──> encoder GND                            │
                                                     GND
```

### The five wiring mistakes that cost the most time

**★ Common ground.** The battery, the motor driver and the ESP32 must share
a ground. Without it the ESP32 sees garbage on every input, and the symptom
is *intermittent nonsense* rather than a clean failure — the worst kind.

**Never power the motors from the ESP32's 5 V pin.** A stalling motor pulls
an amp or more; the ESP32's regulator gives you a few hundred milliamps.
Motors take power from the battery through the driver, always.

**Check your encoder's logic voltage.** Many BO-motor encoders are 3.3 V
tolerant; some are 5 V. Feeding 5 V into an ESP32 GPIO will eventually kill
the pin. If yours is 5 V, use a level shifter or a divider.

**Do not use GPIO34–39 for encoders.** They are input-only *and* have no
internal pull-ups. Most hall encoders need one. `config.h` deliberately uses
16/17/4/23. (GPIO34 *is* used for the battery divider, which is exactly what
an input-only analog pin is for.)

**Add a capacitor across the motor terminals** (0.1 µF ceramic) if the
encoder counts look noisy. Brushed motors are electrically filthy and the
noise couples straight into the encoder lines.

---

## 3. The golden rule of bringup

> **Change one thing, then prove it works, before changing the next.**

Every step below ends with a check you can actually perform. If a check
fails, fix it *there*. Do not proceed hoping a later step will explain it —
with a robot, three unverified changes stacked together produce a symptom
that looks like none of them.

The order is deliberate: each step depends only on the ones before it.

```
   flash ──> motors ──> encoders ──> ticks/rev ──> geometry ──> battery
     └──> PID ──> ROS over USB ──> odometry check ──> LiDAR
                                                        └──> Wi-Fi ──> map ──> mission
```

---

## Step 1 — Flash the ESP32, no motors attached

Nothing is connected except the USB cable. This proves the toolchain, the
board and the protocol before any moving part can hurt anything.

```bash
# On the Mac
brew install platformio      # or: pip install platformio
cd firmware/esp32_robot
pio run -t upload
pio device monitor -b 115200
```

You should see, immediately after boot:

```
VER,esp32-1.0.0
LOG,ready
ENC,0,0,1024
ENC,0,0,1044
BAT,0.00
ERR,command watchdog expired - motors stopped
```

That `ERR` is **correct**. Nothing has sent a `CMD`, so the watchdog cut the
motors. Seeing it proves the safety path works.

Now talk to it by hand:

```
CMD,0,0
PING,1
```

Expect `PONG,1`, and the watchdog error to stop appearing while you keep
sending commands.

**Check ✅** — `VER` on boot, `ENC` lines streaming at about 50 Hz, `PONG`
answering `PING`.

> **If the upload fails:** hold the BOOT button while it says "Connecting...".
> If the port is missing, install the CP2102 or CH340 driver for your board
> and look for `/dev/tty.usbserial-*` or `/dev/tty.SLAB_USBtoUART`.

---

## Step 2 — Motors spin the right way

**Put the robot on a stand so the wheels are off the ground.** Every wheel
test from here on is done with the robot unable to drive off the desk.

Connect the motor driver and battery. Then, in the serial monitor:

```
CMD,0.1,0
```

Both wheels should turn **forward**. Then:

```
CMD,0,0
```

Both stop.

If a wheel turns backwards, **swap that motor's two power wires** at the
driver. Do not try to fix it in software — direction lives in the wiring, and
sorting it out physically keeps the firmware honest.

Now check turning:

```
CMD,0,0.5
```

Positive angular is **counter-clockwise seen from above**, i.e. a left turn:
the **right wheel goes forward, the left wheel goes backward**. This is ROS
convention (REP-103) and the entire navigation stack assumes it. Getting it
backwards makes the robot turn away from every goal it is ever given.

**Check ✅** — `CMD,0.1,0` drives both wheels forward; `CMD,0,0.5` turns the
right wheel forward and the left backward.

---

## Step 3 — Encoders count the right way

Still on the stand, watch the `ENC` lines and turn each wheel **by hand,
forwards**:

```
ENC,0,0,12000
ENC,45,0,12020        <- left count rising: correct
ENC,88,0,12040
```

Both counts must **increase** when the wheel is turned in the forward
direction.

If one counts down, fix it in `firmware/esp32_robot/src/config.h`:

```c
#define LEFT_ENCODER_SIGN   -1     // was 1
```

Reflash and re-check.

> Set the sign **either** in the firmware **or** via `invert_left_encoder` in
> `hardware.yaml` — never both, or they cancel out and you are back where you
> started, having "fixed" it twice.

**Check ✅** — turning either wheel forward by hand increases its count;
turning it backward decreases it.

---

## Step 4 — Measure ticks per revolution

This is the number that converts counts into metres. Guessing it makes
odometry wrong by a constant factor, and everything downstream inherits the
error.

1. Mark the wheel and the chassis with a pen so you can see one full turn.
2. Send `RST` to zero the counters.
3. Turn the wheel by hand **exactly 10 full revolutions**, slowly.
4. Read the count.

```
RST
ENC,0,0,30000
   (turn the wheel 10 times)
ENC,7804,0,52000
```

```
   ticks_per_rev = 7804 / 10 = 780
```

Ten revolutions rather than one, because the error in spotting the exact
mark position is then divided by ten.

Put the result in **both** places:

- `firmware/esp32_robot/src/config.h` → `TICKS_PER_REV`
- `ros_ws/src/robot_hardware/config/hardware.yaml` → `ticks_per_rev`

Then prove they agree:

```bash
python3 scripts/check_geometry_sync.py
```

**Check ✅** — the checker prints `PASS`, and repeating the count experiment
gives the same number within about 1%.

---

## Step 5 — Measure the wheel geometry

Two measurements with a ruler. Both matter more than any software setting.

**Wheel radius.** Measure the wheel diameter including the rubber tyre, with
the robot's weight on it if you can, and halve it. A 65 mm wheel gives
`0.0325`. Being 2 mm out is a 3% distance error — over 20 m that is 60 cm.

**Wheel separation.** The distance between the two drive wheels' *contact
points with the floor* — not between the motor mounts, not the chassis
width.

```
        │◄──────── wheel_separation ────────►│
        │                                    │
     ┌──┴──┐                              ┌──┴──┐
     │wheel│        ┌──────────┐          │wheel│
     └──┬──┘        │  robot   │          └──┬──┘
        │           └──────────┘             │
    ────●───────────────────────────────────●────  floor
```

This single number sets how far the robot thinks it has turned. Get it wrong
and the robot consistently over- or under-rotates — the classic symptom
being "it drives to roughly the right place but ends up facing the wrong
way", which people spend days trying to fix with PID gains.

Update **three** files:

| File | Field |
|---|---|
| `ros_ws/src/robot_description/urdf/common_properties.xacro` | `wheel_radius`, `wheel_separation` |
| `ros_ws/src/robot_hardware/config/hardware.yaml` | `wheel_radius`, `wheel_separation` |
| `firmware/esp32_robot/src/config.h` | `WHEEL_RADIUS_M`, `WHEEL_SEPARATION_M` |

```bash
python3 scripts/check_geometry_sync.py
python3 scripts/validate_urdf.py
```

**Check ✅** — both scripts print `PASS`. Calibrating the separation properly
comes in Step 9.

---

## Step 6 — Calibrate the battery divider

With a 20 kΩ / 10 kΩ divider, 8.4 V arrives at the ADC as 2.8 V — safely
inside the ESP32's range.

Measure the actual pack voltage with a multimeter, then compare with the
`BAT` line:

```
   multimeter says   7.82 V
   BAT says          7.51 V

   BATTERY_CALIBRATION = 7.82 / 7.51 = 1.041
```

Put that in `config.h` and reflash. The ESP32's ADC is noticeably non-linear,
so this correction is normal and expected — do not assume you wired it
wrong.

Then set the empty/full voltages in `hardware.yaml` for your chemistry:

| Pack | full | empty |
|---|---|---|
| 2S Li-ion / LiPo | 8.4 | 6.6 |
| 6 × AA alkaline | 9.0 | 6.0 |
| 6 × AA NiMH | 8.4 | 6.6 |

**Never run a Li-ion pack below its empty voltage.** It damages the cells
permanently and can make them unsafe. The low-battery warning exists for a
reason.

**Check ✅** — `BAT` agrees with a multimeter within about 0.1 V, and the
percentage shown falls as the robot runs.

---

## Step 7 — Calibrate feedforward and tune the PID

Cheap gearmotors have a dead zone and are not linear, so pure PID feels
sluggish and tracks badly at low speed. Feedforward fixes most of it before
PID has to do anything.

### Find the minimum duty that moves the wheel

Temporarily set `PID_KP`, `PID_KI`, `PID_KD` and `PID_FF` to `0` and add a
test that writes a fixed duty — or simply raise the commanded velocity from
zero and watch when the wheels start turning. Whatever duty that corresponds
to is your stiction threshold; put it in `MIN_MOVE_PWM` (the default is 120
out of 1023).

### Measure the feedforward gain

With the robot **on the stand**, command a mid-range speed and read back the
measured wheel speed:

```
CMD,0.2,0
```

`0.2 m/s` with a `0.0325 m` wheel is `0.2 / 0.0325 = 6.15 rad/s`. Note the
duty needed to reach it. Then:

```
   PID_FF = duty_at_that_speed / 6.15
```

The default `38.0` is a reasonable starting guess for a 7.4 V pack and
typical yellow gearmotors. It will be wrong for your motors; measure it.

### Tune, live, with no reflash

`CFG` changes gains at runtime — this is what makes tuning bearable:

```
CFG,kp,0.6
CFG,ki,2.5
CFG,ff,38.0
```

Procedure:

1. `ki = 0`, `kd = 0`. Raise `kp` until the wheel reaches the commanded speed
   quickly without oscillating. Back off 20% from wherever it starts to
   buzz.
2. Raise `ki` until steady-state error disappears (the wheel actually settles
   *at* the target, not near it). Too much `ki` causes slow oscillation.
3. Leave `kd` at 0. Encoder-derived velocity is noisy, and `kd` amplifies
   noise. On a robot this size it earns nothing.

When you are happy, write the values into `config.h` and reflash so they
survive a power cycle.

**Check ✅** — commanding `CMD,0.15,0` and `CMD,0.30,0` produces visibly
different, *stable* wheel speeds, with no buzzing or hunting.

---

## Step 8 — Connect ROS over USB

USB first, always. Wi-Fi adds latency, jitter and a whole extra failure mode;
you want none of that while proving the pipeline.

Find the port:

```bash
ls /dev/tty.* | grep -i -E "usb|slab|wch"
```

If you are running ROS in Docker, pass the device through — uncomment the
`devices:` block in `docker-compose.yml` with your actual device path, and
restart the container.

Then:

```bash
roslaunch robot_hardware hardware.launch transport:=serial \
    serial_port:=/dev/ttyUSB0 lidar:=false
```

In another shell:

```bash
rostopic echo /robot_telemetry        # connected: True, sensible voltage
rostopic echo /odom                   # pose updating as you push the robot
rostopic hz /odom                     # should be around 50 Hz
```

Now drive it. **Put the robot on the floor with space around it:**

```bash
roslaunch robot_gazebo teleop.launch
```

**Check ✅** — arrow keys move the robot, releasing them stops it within half
a second (the deadman), and `/odom` changes as it drives.

---

## Step 9 — Verify odometry against a tape measure

This is the most important calibration in the entire project. Everything
above it inherits these errors.

### Straight-line test

1. Put the robot on the floor. Mark the starting point.
2. `rostopic echo /odom` in another window.
3. Drive straight forward about 2 m with teleop.
4. Measure the real distance with a tape measure. Compare with
   `pose.pose.position.x`.

```
   odometry says   2.08 m
   tape says       2.00 m
   -> odometry over-reports by 4%
   -> wheel_radius is 4% too large: 0.0325 -> 0.0312
```

### Rotation test

1. Mark the robot's heading (a strip of tape on the floor helps).
2. Spin in place through exactly 10 full turns.
3. Compare the accumulated yaw with `10 × 2π = 62.83 rad`.

```
   odometry says   59.9 rad      (under-reports by 4.7%)
   -> the robot turned MORE than odometry thinks
   -> wheel_separation is too large: 0.160 -> 0.1525
```

Ten turns rather than one for the same reason as before: it divides your
reading error by ten.

Which way to adjust:

| Symptom | Fix |
|---|---|
| odometry distance > real distance | decrease `wheel_radius` |
| odometry distance < real distance | increase `wheel_radius` |
| robot turns more than odometry says | decrease `wheel_separation` |
| robot turns less than odometry says | increase `wheel_separation` |

Iterate until both are within about 2%. Update all three files, run
`check_geometry_sync.py`, reflash.

**Check ✅** — a 2 m drive reads within 4 cm; 10 turns reads within 1.2 rad.

> Do not skip this because it is tedious. A 5% odometry error means AMCL is
> constantly fighting to correct a robot that keeps drifting, and navigation
> will feel unreliable in a way that no configuration change can fix.

---

## Step 10 — Add the LiDAR

The RPLiDAR is a separate USB device with its own ROS driver. The firmware
knows nothing about it.

```bash
ls /dev/tty.*        # find the second adapter
roslaunch robot_hardware hardware.launch transport:=serial lidar:=true \
    lidar_port:=/dev/ttyUSB1
```

Check it:

```bash
rostopic hz /scan                 # about 10 Hz
rostopic echo /scan -n1 | head    # ranges, and frame_id: laser_link
```

Then look at it in RViz: set Fixed Frame to `laser_link`, add a LaserScan
display on `/scan`. Walk around the robot — the dots should move with you.

**Mount the LiDAR so it is level, unobstructed through 360°, and at the same
height you put it in the URDF** (`lidar_z_offset`). If a chassis post blocks
part of the sweep, AMCL will see a permanent phantom obstacle in that
direction and localisation will suffer.

Confirm the mounting matches the model:

```bash
rosrun tf tf_echo base_link laser_link
```

It should match the URDF's `laser_joint` origin. If the real LiDAR is 3 cm
higher than the model says, update `common_properties.xacro`.

**Check ✅** — `/scan` at 10 Hz, the room's shape recognisable in RViz, and
no phantom returns from the robot's own body.

---

## Step 11 — Cut the cable: switch to Wi-Fi

Only now, with everything proven over USB.

1. Put your network details in `config.h`:

```c
#define WIFI_SSID      "your-network"
#define WIFI_PASSWORD  "your-password"
```

2. Reflash over USB, then watch the monitor for the IP address:

```
LOG,wifi connected
LOG,ip=192.168.1.50
```

3. Test the link with no ROS at all:

```bash
python3 ros_ws/src/robot_hardware/scripts/esp32_console.py --tcp 192.168.1.50
```

Type `PING,1`, expect `PONG,1`. Type `CMD,0.1,0` (**on the stand**), expect
the wheels to turn.

4. Then point ROS at it:

```bash
roslaunch robot_bringup real.launch transport:=tcp esp32_ip:=192.168.1.50
```

Watch `link_latency_ms` in `/robot_telemetry`. Under 20 ms is fine; over
100 ms and the robot will feel sloppy — move closer to the access point, or
use the 2.4 GHz band, which has better range than 5 GHz.

> **College Wi-Fi is often hostile to this.** Many campus networks use client
> isolation, which blocks your Mac from reaching the ESP32 even though both
> are "connected". If `PING` never answers, tether a phone hotspot or use a
> cheap travel router, and put both devices on that.

**Check ✅** — the robot drives over Wi-Fi with the USB cable unplugged, and
latency stays under about 50 ms.

---

## Step 12 — Map your building

```bash
# Terminal 1 - the robot, no map yet
roslaunch robot_hardware hardware.launch transport:=tcp esp32_ip:=192.168.1.50
roslaunch robot_description description.launch use_gazebo:=false

# Terminal 2 - SLAM
roslaunch robot_navigation mapping.launch sim:=false

# Terminal 3 - drive
roslaunch robot_gazebo teleop.launch
```

Watch the map build in RViz. Then:

```bash
rosrun map_server map_saver -f ~/floor1
cp ~/floor1.* ros_ws/src/robot_navigation/maps/
```

Mapping technique, in order of how much difference it makes:

- **Drive slowly.** Faster than about 0.2 m/s and wheel slip corrupts the
  odometry gmapping depends on.
- **Turn gently.** Spinning fast is the single worst thing for map quality.
- **Close loops.** Come back to where you started so gmapping can correct
  drift across the whole map.
- **Cover everything you want to navigate.** Unmapped space cannot be
  planned through.

Then check your destinations sit in reachable space:

```bash
python3 scripts/check_destinations.py --map maps/floor1.yaml
```

**Check ✅** — the saved map looks like the actual building, corridors are
straight, and the destination checker passes.

---

## Step 13 — First autonomous mission

```bash
roslaunch robot_bringup real.launch transport:=tcp esp32_ip:=192.168.1.50 \
    map:=$(rospack find robot_navigation)/maps/floor1.yaml
```

In RViz:

1. **Set the initial pose.** Use *2D Pose Estimate* and click where the robot
   actually is, dragging in the direction it faces. **Do not skip this.** A
   robot that thinks it is somewhere else will drive confidently into a
   wall, and this is by far the most common cause of a first-mission
   failure.
2. Check the particle cloud tightens as you nudge the robot forward.
3. Use *2D Nav Goal* to send it somewhere close and easy first.

**Keep a hand near the power switch for the first few runs.**

When that works, do it properly through the mission layer:

```bash
rosservice call /start_mission "{mission_id: 1, destination_name: 'AI Lab',
  goal_x: 3.8, goal_y: 3.4, goal_yaw: 1.57, preempt: false}"

rostopic echo /mission_status
```

**Check ✅** — the robot plans a path, drives it, avoids an obstacle you put
in its way, arrives, and `/mission_status` reports `SUCCEEDED`.

---

## Troubleshooting

### Nothing happens when ROS starts

```bash
rostopic echo /hardware_connected
```

`false` means the bridge cannot reach the ESP32. Check, in this order: the
serial port name; whether another program (the PlatformIO monitor!) has the
port open; the baud rate; for Wi-Fi, whether `esp32_console.py` can reach it
at all.

### The robot drives in a curve when commanded straight

One wheel is slower than the other. Likely causes:

- **The PID is not tracking.** Compare `left_wheel_rps` and `right_wheel_rps`
  in `/robot_telemetry` — if they differ while driving straight, tune the
  gains.
- **A wheel is mechanically stiff.** Spin both by hand and feel the
  difference.
- **`ticks_per_rev` differs between the two motors.** Cheap motors are not
  identical; measure each and use the average, or accept a small bias.

### The robot turns roughly twice as far as commanded

`wheel_separation` is about half of reality — or you measured the chassis
width instead of the wheel contact points. Re-measure, update all three
files, run `check_geometry_sync.py`.

### Odometry drifts badly, AMCL keeps losing the robot

Expected to some degree, which is *why* AMCL exists. If it is severe:

- Redo Step 9 calibration.
- Drive more slowly; slip destroys odometry.
- Raise `odom_alpha1..4` in `amcl_params.yaml` so AMCL trusts odometry less.
- Check the LiDAR is not partly blocked by the chassis.

### move_base says "no path"

```bash
python3 scripts/check_nav_config.py     # inflation sealing doorways?
python3 scripts/check_destinations.py   # goal inside a wall?
```

If both pass, the robot's *believed* position is probably wrong. Re-set the
initial pose.

### Motors buzz but do not turn

`MIN_MOVE_PWM` is too low, the battery is flat, or the motor driver is not
getting battery voltage on `VM`. Check the pack voltage under load — a tired
pack that reads 7.4 V at rest can collapse to 5 V the moment the motors
start.

### Encoder counts jump wildly

Electrical noise from the motors. Add 0.1 µF capacitors across the motor
terminals, keep encoder wires away from motor wires, and make sure the
common ground is solid.

### It works on USB but not on Wi-Fi

Client isolation on the network (see Step 11), the wrong IP, or the ESP32
silently failing to join. Watch the serial monitor during boot — it prints
either `LOG,ip=...` or `ERR,wifi connect failed`.

---

## Safety

Small robots are not dangerous; batteries and unattended autonomy are.

- **Wheels off the ground** for every test until Step 8.
- **Know where the power switch is**, and keep a hand near it during the first
  autonomous runs.
- **Never charge Li-ion unattended**, and never run a pack below its empty
  voltage.
- **Check polarity twice** before connecting the battery. Reversed polarity
  kills the ESP32 and the driver instantly, and it is the one mistake with no
  recovery.
- **Disconnect the battery** before rewiring anything.
- **Both watchdogs must stay enabled.** The firmware cuts the motors after
  500 ms without a command, and the bridge commands a stop after 500 ms
  without `/cmd_vel`. They are the reason a dropped Wi-Fi link stops the
  robot instead of leaving it driving into a wall at full speed.
