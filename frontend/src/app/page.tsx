"use client";

/** Dashboard: the fleet at a glance, updating live. */

import { useCallback, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { formatAgo, formatDistance, formatDuration } from "@/lib/format";
import { useLive, usePoll } from "@/lib/useLive";
import type { LiveMessage, Mission, Robot } from "@/lib/types";
import {
  Battery,
  Empty,
  ErrorNote,
  Panel,
  Progress,
  RobotLink,
  Stat,
  StatusBadge,
} from "@/components/ui";

export default function Dashboard() {
  const [robots, setRobots] = useState<Robot[]>([]);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [nextRobots, nextMissions] = await Promise.all([
        api.listRobots(),
        api.listMissions({ limit: 8 }),
      ]);
      setRobots(nextRobots);
      setMissions(nextMissions);
      setError(null);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    }
  }, []);

  usePoll(reload, 4000);

  // WebSocket updates are merged into the existing rows rather than
  // triggering a refetch, so the numbers move the instant the robot does.
  const live = useLive(
    useCallback((message: LiveMessage) => {
      if (message.type === "robot_update") {
        setRobots((current) =>
          current.map((robot) =>
            robot.id === message.data.id
              ? {
                  ...robot,
                  status: message.data.status,
                  battery_percent: message.data.battery_percent,
                  x: message.data.x,
                  y: message.data.y,
                  last_error: message.data.last_error,
                }
              : robot,
          ),
        );
      } else if (message.type === "mission_update") {
        setMissions((current) =>
          current.map((mission) =>
            mission.id === message.data.id
              ? {
                  ...mission,
                  status: message.data.status,
                  percent_complete: message.data.percent_complete,
                  distance_m: message.data.distance_m,
                  duration_s: message.data.duration_s,
                }
              : mission,
          ),
        );
      }
    }, []),
  );

  const active = missions.filter(
    (mission) => mission.status === "NAVIGATING" || mission.status === "QUEUED",
  );
  const online = robots.filter((robot) => robot.status !== "OFFLINE");

  return (
    <div className="space-y-6">
      {error && <ErrorNote message={error} />}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat
          label="Robots online"
          value={`${online.length} / ${robots.length}`}
        />
        <Stat label="Active missions" value={active.length} />
        <Stat
          label="Fleet distance"
          value={formatDistance(
            missions.reduce((sum, mission) => sum + mission.distance_m, 0),
          )}
          hint="recent missions"
        />
        <Stat
          label="Live feed"
          value={live ? "streaming" : "polling"}
          hint={live ? "websocket connected" : "websocket reconnecting"}
        />
      </div>

      <Panel
        title="Robots"
        action={
          <Link
            href="/robots"
            className="text-xs text-ink-dim hover:text-ink"
          >
            manage →
          </Link>
        }
      >
        {robots.length === 0 ? (
          <Empty>
            No robots yet. Run <code>python3 backend/seed.py</code> to create
            RB001 and the simulated lab.
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-[11px] uppercase tracking-widest text-ink-dim">
                <tr>
                  <th className="pb-2 font-medium">Robot</th>
                  <th className="pb-2 font-medium">Status</th>
                  <th className="pb-2 font-medium">Battery</th>
                  <th className="pb-2 font-medium">Position</th>
                  <th className="pb-2 font-medium">Last seen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-edge">
                {robots.map((robot) => (
                  <tr key={robot.id}>
                    <td className="py-2.5">
                      <RobotLink id={robot.id}>{robot.code}</RobotLink>
                      <div className="text-xs text-ink-dim">
                        {robot.name}
                        {robot.mode === "SIMULATED" && " · simulated"}
                      </div>
                    </td>
                    <td className="py-2.5">
                      <StatusBadge status={robot.status} />
                      {robot.last_error && (
                        <div className="mt-1 text-xs text-bad">
                          {robot.last_error}
                        </div>
                      )}
                    </td>
                    <td className="py-2.5">
                      <Battery percent={robot.battery_percent} />
                    </td>
                    <td className="tnum py-2.5 text-ink-dim">
                      {robot.x === null || robot.y === null
                        ? "—"
                        : `${robot.x.toFixed(2)}, ${robot.y.toFixed(2)}`}
                    </td>
                    <td className="py-2.5 text-ink-dim">
                      {formatAgo(robot.last_seen)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel
        title="Active missions"
        action={
          <Link
            href="/missions"
            className="text-xs text-ink-dim hover:text-ink"
          >
            deploy →
          </Link>
        }
      >
        {active.length === 0 ? (
          <Empty>Nothing running. Deploy a mission from the Missions page.</Empty>
        ) : (
          <ul className="space-y-4">
            {active.map((mission) => {
              const robot = robots.find((item) => item.id === mission.robot_id);
              return (
                <li key={mission.id}>
                  <div className="mb-1.5 flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-medium">
                      {robot?.code ?? `robot ${mission.robot_id}`}
                    </span>
                    <span className="text-ink-dim">→</span>
                    <span>{mission.destination_name}</span>
                    <StatusBadge status={mission.status} kind="mission" />
                    <span className="tnum ml-auto text-xs text-ink-dim">
                      {formatDistance(mission.distance_m)} ·{" "}
                      {formatDuration(mission.duration_s)}
                    </span>
                  </div>
                  <Progress percent={mission.percent_complete} />
                </li>
              );
            })}
          </ul>
        )}
      </Panel>

      <Panel title="Recent missions">
        {missions.length === 0 ? (
          <Empty>No missions yet.</Empty>
        ) : (
          <ul className="divide-y divide-edge text-sm">
            {missions.map((mission) => (
              <li
                key={mission.id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2"
              >
                <Link
                  href={`/missions/${mission.id}`}
                  className="tnum text-ink-dim hover:text-ink"
                >
                  #{mission.id}
                </Link>
                <span>{mission.destination_name}</span>
                <StatusBadge status={mission.status} kind="mission" />
                <span className="ml-auto text-xs text-ink-dim">
                  {formatAgo(mission.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
