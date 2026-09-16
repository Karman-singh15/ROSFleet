#!/usr/bin/env python3
"""
check_nav_config.py - catch navigation-config mistakes that look like
mysterious robot behaviour.

The three classic ones, all silent:

  1. DWA is told the robot is faster than it is.
     move_base plans for 1.0 m/s, the motors saturate at 0.35 m/s, the robot
     falls behind its own trajectory, overshoots every corner and oscillates.
     Looks like "bad PID tuning". Is not.

  2. The inflation radius is wider than half a doorway.
     Every doorway becomes lethal cost, the global planner reports "no path",
     and the robot refuses to move with no visible obstacle.

  3. The footprint does not match the chassis.
     Too small and it clips door frames; too large and it will not fit
     through gaps it physically fits through.

    python3 scripts/check_nav_config.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAV = os.path.join(ROOT, "ros_ws/src/robot_navigation/config")
HARDWARE_YAML = os.path.join(ROOT, "ros_ws/src/robot_hardware/config/hardware.yaml")

# A standard Indian/office interior door is ~0.75-0.90 m. Corridors wider.
NARROWEST_GAP_M = 0.75


def load(path):
    import yaml
    with open(path) as handle:
        return yaml.safe_load(handle)


def main():
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("ERROR: pip install pyyaml")
        return 2

    hardware = load(HARDWARE_YAML)
    dwa = load(os.path.join(NAV, "dwa_local_planner.yaml"))["DWAPlannerROS"]
    common = load(os.path.join(NAV, "costmap_common.yaml"))
    local = load(os.path.join(NAV, "costmap_local.yaml"))["local_costmap"]
    move_base = load(os.path.join(NAV, "move_base_params.yaml"))

    problems = []
    warnings = []

    # --- 1. planner limits vs the actual drivetrain --------------------
    hw_linear = hardware["max_linear_velocity"]
    hw_angular = hardware["max_angular_velocity"]
    print("planner limits vs hardware")
    print("  max_vel_x      %.2f m/s   hardware allows %.2f m/s" %
          (dwa["max_vel_x"], hw_linear))
    print("  max_vel_theta  %.2f rad/s hardware allows %.2f rad/s" %
          (dwa["max_vel_theta"], hw_angular))
    if dwa["max_vel_x"] > hw_linear + 1e-9:
        problems.append("DWA max_vel_x (%.2f) exceeds the robot's max_linear_velocity "
                        "(%.2f)" % (dwa["max_vel_x"], hw_linear))
    if dwa["max_vel_theta"] > hw_angular + 1e-9:
        problems.append("DWA max_vel_theta (%.2f) exceeds max_angular_velocity "
                        "(%.2f)" % (dwa["max_vel_theta"], hw_angular))
    if dwa["max_vel_x"] > hw_linear * 0.95:
        warnings.append("DWA max_vel_x leaves no headroom; the bridge will clamp "
                        "commands the planner expects to be honoured")

    # --- 2. footprint vs chassis -------------------------------------
    footprint = common["footprint"]
    xs = [point[0] for point in footprint]
    ys = [point[1] for point in footprint]
    length = max(xs) - min(xs)
    width = max(ys) - min(ys)
    half_width = max(abs(min(ys)), abs(max(ys)))
    circumscribed = max((x ** 2 + y ** 2) ** 0.5 for x, y in footprint)
    print("\nfootprint")
    print("  %.2f m long x %.2f m wide, circumscribed radius %.3f m" %
          (length, width, circumscribed))
    if width < hardware["wheel_separation"]:
        problems.append("footprint width (%.2f m) is narrower than the wheelbase "
                        "(%.2f m) - the wheels stick out of the footprint" %
                        (width, hardware["wheel_separation"]))

    # --- 3. inflation vs the narrowest gap ----------------------------
    inflation = common["inflation_layer"]["inflation_radius"]
    # A gap is passable only if free space remains between the two inflated
    # walls, i.e. gap > 2*inflation is comfortable; gap > 2*circumscribed is
    # the hard physical limit.
    print("\ninflation")
    print("  inflation_radius %.2f m; narrowest gap assumed %.2f m" %
          (inflation, NARROWEST_GAP_M))
    print("  inflated corridor leaves %.2f m of free space" %
          (NARROWEST_GAP_M - 2 * inflation))
    if 2 * circumscribed >= NARROWEST_GAP_M:
        problems.append("the robot's circumscribed radius (%.3f m) cannot fit "
                        "through a %.2f m gap at all" %
                        (circumscribed, NARROWEST_GAP_M))
    elif 2 * inflation >= NARROWEST_GAP_M:
        problems.append("inflation_radius %.2f m seals off a %.2f m doorway; "
                        "the planner will report 'no path' with nothing in the way"
                        % (inflation, NARROWEST_GAP_M))
    if inflation < half_width:
        warnings.append("inflation_radius (%.2f m) is smaller than the robot's "
                        "half-width (%.2f m); it may clip corners" %
                        (inflation, half_width))

    # --- 4. loop rates must be consistent -----------------------------
    print("\nrates")
    controller_hz = move_base["controller_frequency"]
    local_hz = local["update_frequency"]
    print("  move_base controller %.1f Hz, local costmap update %.1f Hz" %
          (controller_hz, local_hz))
    if controller_hz > local_hz:
        problems.append("controller_frequency (%.1f Hz) is faster than the local "
                        "costmap update rate (%.1f Hz) - the planner repeatedly "
                        "replans on stale obstacle data" % (controller_hz, local_hz))
    if abs(dwa["controller_frequency"] - controller_hz) > 1e-9:
        warnings.append("DWAPlannerROS/controller_frequency (%.1f) differs from "
                        "move_base/controller_frequency (%.1f)" %
                        (dwa["controller_frequency"], controller_hz))

    # --- 5. the local window must contain the lookahead ---------------
    lookahead = dwa["sim_time"] * dwa["max_vel_x"]
    print("\nlocal window")
    print("  DWA looks %.2f m ahead; local costmap is %.1f x %.1f m "
          "(%.2f m in front)" % (lookahead, local["width"], local["height"],
                                 local["width"] / 2.0))
    if lookahead > local["width"] / 2.0:
        problems.append("DWA's %.2f m lookahead extends past the edge of the "
                        "%.1f m local costmap; trajectories are scored against "
                        "unknown space" % (lookahead, local["width"]))

    # --- 6. sensor range sanity ---------------------------------------
    obstacle_range = common["obstacle_layer"]["obstacle_range"]
    raytrace_range = common["obstacle_layer"]["raytrace_range"]
    if raytrace_range < obstacle_range:
        problems.append("raytrace_range (%.1f) < obstacle_range (%.1f): obstacles "
                        "get marked but never cleared, so the costmap fills with "
                        "ghosts" % (raytrace_range, obstacle_range))

    # --- 7. the local costmap must not track unknown space -------------
    # costmap_common.yaml is loaded into BOTH namespaces, then the
    # per-costmap file is loaded over it, so the local value is whichever
    # costmap_local.yaml sets - falling back to common's.
    local_plugins = [p["name"] for p in local.get("plugins", [])]
    local_unknown = local.get("obstacle_layer", {}).get(
        "track_unknown_space", common["obstacle_layer"]["track_unknown_space"])
    print("local costmap unknown space")
    print("  track_unknown_space %s   static_layer %s"
          % (local_unknown, "static_layer" in local_plugins))
    if local_unknown and "static_layer" not in local_plugins:
        problems.append("local costmap has track_unknown_space: true but no "
                        "static_layer, so every cell starts unknown and the "
                        "laser can never clear the robot's own footprint; "
                        "footprintCost() returns -1, DWA rejects every "
                        "trajectory and rotate_recovery refuses to turn")

    print()
    for warning in warnings:
        print("WARN  %s" % warning)
    if problems:
        print("\nFAIL - navigation configuration problems:")
        for problem in problems:
            print("  * %s" % problem)
        return 1
    print("PASS: navigation configuration is self-consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
