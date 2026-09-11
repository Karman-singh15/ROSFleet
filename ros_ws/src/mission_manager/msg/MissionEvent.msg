# One timestamped line in a mission's log.
# Published on /mission_events; the backend stores these so the website can
# show "14:32:08  Obstacle detected / 14:32:10  Path replanned".

Header header

int32  mission_id
string level        # INFO | WARN | ERROR
string event        # machine-readable: MISSION_CREATED, GOAL_SENT,
                    # NAVIGATING, REPLANNED, RECOVERY, ARRIVED, FAILED,
                    # CANCELLED, ABORTED_BY_SAFETY
string detail       # human-readable text
