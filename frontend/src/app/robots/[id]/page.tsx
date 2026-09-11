"use client";

import { use, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { degrees, formatAgo, formatDistance, formatDuration } from "@/lib/format";
import { usePoll } from "@/lib/useLive";
import type { Mission, Robot } from "@/lib/types";
import {
  Battery,
  Button,
  Empty,
  ErrorNote,
  Panel,
  Progress,
  Stat,
  StatusBadge,
} from "@/components/ui";

export default function RobotDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const robotId = Number(id);

  const [robot, setRobot] = useState<Robot | null>(null);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [error, setError] = useState<string | null>(null);

  usePoll(async () => {
    try {
      const [nextRobot, nextMissions] = await Promise.all([
        api.getRobot(robotId),
        api.listMissions({ robot_id: robotId, limit: 20 }),
      ]);
      setRobot(nextRobot);
      setMissions(nextMissions);
      setError(null);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    }
  }, 2000);

  const active = missions.find(
    (mission) => mission.status === "NAVIGATING" || mission.status === "QUEUED",
  );

  const stop = async () => {
    if (!active) return;
    try {
      await api.cancelMission(active.id);
      setMissions(await api.listMissions({ robot_id: robotId, limit: 20 }));
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    }
  };

  if (error && !robot) return <ErrorNote message={error} />;
  if (!robot) return <Empty>Loading…</Empty>;

  return (
    <div className="space-y-6">
      {error && <ErrorNote message={error} />}

      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{robot.code}</h1>
        <StatusBadge status={robot.status} />
        <span className="text-sm text-ink-dim">
          {robot.name} · {robot.mode.toLowerCase()}
        </span>
        {active && (
          <Button variant="danger" onClick={stop} className="ml-auto">
            Stop robot
          </Button>
        )}
      </div>

      {robot.last_error && <ErrorNote message={robot.last_error} />}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat
          label="Battery"
          value={<Battery percent={robot.battery_percent} />}
          hint={
            robot.battery_voltage !== null
              ? `${robot.battery_voltage.toFixed(2)} V`
              : undefined
          }
        />
        <Stat
          label="Position"
          value={
            robot.x === null || robot.y === null
              ? "—"
              : `${robot.x.toFixed(2)}, ${robot.y.toFixed(2)}`
          }
          hint={`heading ${degrees(robot.yaw)}`}
        />
        <Stat
          label="Speed"
          value={
            robot.linear_velocity === null
              ? "—"
              : `${robot.linear_velocity.toFixed(2)} m/s`
          }
        />
        <Stat
          label="Last seen"
          value={formatAgo(robot.last_seen)}
          hint={robot.firmware_version ?? undefined}
        />
      </div>

      {active && (
        <Panel title="Current mission">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
            <span>{active.destination_name}</span>
            <StatusBadge status={active.status} kind="mission" />
            <span className="tnum ml-auto text-xs text-ink-dim">
              {formatDistance(active.distance_m)} ·{" "}
              {formatDuration(active.duration_s)}
            </span>
          </div>
          <Progress percent={active.percent_complete} />
        </Panel>
      )}

      <Panel title="Mission history">
        {missions.length === 0 ? (
          <Empty>This robot has not run any missions yet.</Empty>
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
                <span className="tnum text-xs text-ink-dim">
                  {formatDistance(mission.distance_m)} ·{" "}
                  {formatDuration(mission.duration_s)}
                </span>
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
