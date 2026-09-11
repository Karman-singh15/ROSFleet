# Low-level health/state of the physical robot.
# Published at ~5 Hz by robot_hardware/hardware_bridge.py (real robot)
# or by robot_hardware/fake_telemetry.py (simulation).

Header header

bool   connected          # is the ESP32 link alive right now?
float32 battery_voltage   # volts, straight from the divider on the ESP32
float32 battery_percent   # 0-100, mapped from voltage via config
int32  left_ticks         # cumulative encoder counts since boot
int32  right_ticks
float32 left_wheel_rps    # measured wheel speed, revolutions/second
float32 right_wheel_rps
float32 front_distance    # metres, ultrasonic/ToF bumper sensor; -1 if absent
float32 link_latency_ms   # round-trip time of the last PING
string  firmware_version
string  last_error        # "" when healthy
