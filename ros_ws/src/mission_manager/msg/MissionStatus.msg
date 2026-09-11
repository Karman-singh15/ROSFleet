# Live state of the robot's current mission.
# Published at 2 Hz on /mission_status, latched, so a backend that connects
# late immediately learns what the robot is doing.

Header header

# Mission identity. mission_id is assigned by the BACKEND (it is the
# database row id) and passed through unchanged, so the website can match
# this message to the mission it created.
int32   mission_id
string  destination_name

# State machine. Exactly one of:
#   IDLE      - no mission
#   QUEUED    - accepted, not yet sent to move_base
#   NAVIGATING- move_base is actively driving
#   SUCCEEDED - arrived within tolerance
#   FAILED    - move_base gave up, or the robot was unreachable
#   CANCELLED - a human or the backend stopped it
string  state

# Progress
float32 distance_remaining   # m, along the current global plan
float32 distance_travelled   # m, integrated from /odom since mission start
float32 elapsed_seconds
float32 percent_complete     # 0-100, by distance

# Where the robot is right now, in the map frame
float32 current_x
float32 current_y
float32 current_yaw

# Goal pose in the map frame
float32 goal_x
float32 goal_y
float32 goal_yaw

string  message              # human-readable detail, e.g. a failure reason
