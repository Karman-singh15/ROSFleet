#!/usr/bin/env python3
"""
check_bringup_parity.py - enforce the project's central architectural claim.

THE CLAIM: simulation and real hardware are interchangeable, because
everything above the robot layer is the same in both.

Concretely, in robot_bringup/launch/sim.launch and real.launch:

    identical in both     navigation, mission_manager, rosbridge
    only in sim           robot_gazebo/simulation.launch
    only in real          robot_description + robot_hardware

This is the kind of invariant that rots silently. Someone adds a node to
sim.launch to try something, forgets to add it to real.launch, and months
later the real robot behaves differently for a reason nobody can find - while
every document still claims the two are equivalent.

Every document in docs/ makes this claim and invites the reader to check it.
This script is that check, run automatically.

    python3 scripts/check_bringup_parity.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCH = os.path.join(ROOT, "ros_ws/src/robot_bringup/launch")

SIM = os.path.join(LAUNCH, "sim.launch")
REAL = os.path.join(LAUNCH, "real.launch")

# The layers that MUST be identical in both bringup files.
SHARED = {
    "robot_navigation/launch/navigation.launch",
    "mission_manager/launch/mission_manager.launch",
    "robot_bringup/launch/rosbridge.launch",
}

# The robot layer: what each file is allowed to have that the other does not.
SIM_ONLY = {"robot_gazebo/launch/simulation.launch"}
REAL_ONLY = {
    "robot_description/launch/description.launch",
    "robot_hardware/launch/hardware.launch",
}


def includes(path):
    """Every $(find pkg)/path included by a launch file, as 'pkg/path'."""
    text = open(path).read()
    found = set()
    for package, tail in re.findall(r'file="\$\(find ([^)]+)\)([^"]+)"', text):
        found.add("%s%s" % (package, tail))
    return found


def main():
    for path in (SIM, REAL):
        if not os.path.exists(path):
            print("FAIL: missing %s" % os.path.relpath(path, ROOT))
            return 1

    sim = includes(SIM)
    real = includes(REAL)

    shared = sim & real
    sim_only = sim - real
    real_only = real - sim

    print("identical in both bringup files:")
    for name in sorted(shared) or ["(none)"]:
        print("   %s" % name)
    print("\nonly in sim.launch:")
    for name in sorted(sim_only) or ["(none)"]:
        print("   %s" % name)
    print("\nonly in real.launch:")
    for name in sorted(real_only) or ["(none)"]:
        print("   %s" % name)
    print()

    problems = []

    missing_shared = SHARED - shared
    if missing_shared:
        problems.append(
            "these must be included IDENTICALLY in both, but are not: %s"
            % ", ".join(sorted(missing_shared)))

    # Anything differing that is not part of the robot layer breaks the claim.
    unexpected_sim = sim_only - SIM_ONLY
    unexpected_real = real_only - REAL_ONLY
    if unexpected_sim:
        problems.append(
            "sim.launch includes %s, which real.launch does not. If this is "
            "part of the robot, add it to SIM_ONLY here; otherwise the two "
            "stacks have diverged and the architecture claim is no longer true"
            % ", ".join(sorted(unexpected_sim)))
    if unexpected_real:
        problems.append(
            "real.launch includes %s, which sim.launch does not. Same "
            "question: robot layer, or divergence?"
            % ", ".join(sorted(unexpected_real)))

    if problems:
        print("FAIL - simulation and hardware are no longer interchangeable:")
        for problem in problems:
            print("  * %s" % problem)
        print("\nEvery document in docs/ claims they are. Fix the launch files,")
        print("or update the claim and this script together.")
        return 1

    print("PASS: navigation, missions and the bridge are identical in both; "
          "only the robot layer differs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
