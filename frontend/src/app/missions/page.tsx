"use client";

/** Deploy a mission, and watch every mission's progress. */

import { useCallback, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { formatAgo, formatDistance, formatDuration } from "@/lib/format";
import { useLive, usePoll } from "@/lib/useLive";
import type { Destination, LiveMessage, Mission, Robot } from "@/lib/types";
import {
  Button,
  Empty,
  ErrorNote,
  Panel,
  Progress,
  StatusBadge,
} from "@/components/ui";

export default function MissionsPage() {
  const [robots, setRobots] = useState<Robot[]>([]);
  const [destinations, setDestinations] = useState<Destination[]>([]);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [robotId, setRobotId] = useState<number | "">("");
  const [destinationId, setDestinationId] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [nextRobots, nextDestinations, nextMissions] = await Promise.all([
        api.listRobots(),
        api.listDestinations(),
        api.listMissions({ limit: 50 }),
      ]);
      setRobots(nextRobots);
      setDestinations(nextDestinations);
      setMissions(nextMissions);
      setError(null);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    }
  }, []);

  usePoll(reload, 3000);

  useLive(
    useCallback((message: LiveMessage) => {
      if (message.type !== "mission_update") return;
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
    }, []),
  );

  const deploy = async (event: React.FormEvent) => {
    event.preventDefault();
    if (robotId === "" || destinationId === "") return;
    setBusy(true);
    try {
      await api.createMission({
        robot_id: Number(robotId),
        destination_id: Number(destinationId),
      });
      await reload();
      setError(null);
    } catch (exc) {
      // The backend's own message says exactly why - "robot is already
      // running mission 12", "not connected to ROS" - so show it verbatim.
      setError(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async (id: number) => {
    try {
      await api.cancelMission(id);
      await reload();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    }
  };

  const select =
    "w-full rounded border border-edge bg-panel-2 px-2 py-1.5 text-sm text-ink outline-none focus:border-busy";

  return (
    <div className="space-y-6">
      {error && <ErrorNote message={error} />}

      <Panel title="Deploy a mission">
        {robots.length === 0 || destinations.length === 0 ? (
          <Empty>
            You need at least one robot and one destination. Run{" "}
            <code>python3 backend/seed.py</code>.
          </Empty>
        ) : (
          <form
            onSubmit={deploy}
            className="grid gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
          >
            <label className="text-xs text-ink-dim">
              Robot
              <select
                value={robotId}
                onChange={(event) =>
                  setRobotId(event.target.value ? Number(event.target.value) : "")
                }
                className={`mt-1 ${select}`}
              >
                <option value="">Select a robot…</option>
                {robots.map((robot) => (
                  <option key={robot.id} value={robot.id}>
                    {robot.code} — {robot.status.toLowerCase()}
                  </option>
                ))}
              </select>
            </label>

            <label className="text-xs text-ink-dim">
              Destination
              <select
                value={destinationId}
                onChange={(event) =>
                  setDestinationId(
                    event.target.value ? Number(event.target.value) : "",
                  )
                }
                className={`mt-1 ${select}`}
              >
                <option value="">Select a destination…</option>
                {destinations.map((destination) => (
                  <option key={destination.id} value={destination.id}>
                    {destination.name}
                  </option>
                ))}
              </select>
            </label>

            <Button
              type="submit"
              disabled={busy || robotId === "" || destinationId === ""}
            >
              {busy ? "Deploying…" : "Deploy mission"}
            </Button>
          </form>
        )}
      </Panel>

      <Panel title="Missions">
        {missions.length === 0 ? (
          <Empty>No missions yet.</Empty>
        ) : (
          <ul className="space-y-4">
            {missions.map((mission) => {
              const robot = robots.find((item) => item.id === mission.robot_id);
              const active =
                mission.status === "NAVIGATING" || mission.status === "QUEUED";
              return (
                <li
                  key={mission.id}
                  className="rounded border border-edge bg-panel-2 p-3"
                >
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
                    <Link
                      href={`/missions/${mission.id}`}
                      className="tnum text-ink-dim hover:text-ink"
                    >
                      #{mission.id}
                    </Link>
                    <span className="font-medium">
                      {robot?.code ?? `robot ${mission.robot_id}`}
                    </span>
                    <span className="text-ink-dim">→</span>
                    <span>{mission.destination_name}</span>
                    <StatusBadge status={mission.status} kind="mission" />
                    <span className="tnum ml-auto text-xs text-ink-dim">
                      {formatDistance(mission.distance_m)} ·{" "}
                      {formatDuration(mission.duration_s)} ·{" "}
                      {formatAgo(mission.created_at)}
                    </span>
                    {active && (
                      <Button variant="ghost" onClick={() => cancel(mission.id)}>
                        Cancel
                      </Button>
                    )}
                  </div>
                  {active && <Progress percent={mission.percent_complete} />}
                  {mission.failure_reason && (
                    <p className="mt-1 text-xs text-bad">
                      {mission.failure_reason}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Panel>
    </div>
  );
}
