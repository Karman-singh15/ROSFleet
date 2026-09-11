"use client";

/** One mission, with the timestamped log that makes failures explainable. */

import { use, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { formatDistance, formatDuration } from "@/lib/format";
import { usePoll } from "@/lib/useLive";
import type { MissionDetail } from "@/lib/types";
import {
  Button,
  Empty,
  ErrorNote,
  Panel,
  Progress,
  Stat,
  StatusBadge,
} from "@/components/ui";

const LEVEL_COLOURS: Record<string, string> = {
  INFO: "text-ink-dim",
  WARN: "text-warn",
  ERROR: "text-bad",
};

export default function MissionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const missionId = Number(id);

  const [mission, setMission] = useState<MissionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  usePoll(async () => {
    try {
      setMission(await api.getMission(missionId));
      setError(null);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    }
  }, 2000);

  if (error && !mission) return <ErrorNote message={error} />;
  if (!mission) return <Empty>Loading…</Empty>;

  const active =
    mission.status === "NAVIGATING" || mission.status === "QUEUED";

  return (
    <div className="space-y-6">
      {error && <ErrorNote message={error} />}

      <div className="flex flex-wrap items-center gap-3">
        <h1 className="tnum text-xl font-semibold">Mission #{mission.id}</h1>
        <StatusBadge status={mission.status} kind="mission" />
        <span className="text-sm text-ink-dim">
          → {mission.destination_name}
        </span>
        {active && (
          <Button
            variant="danger"
            className="ml-auto"
            onClick={async () => {
              try {
                await api.cancelMission(mission.id);
                setMission(await api.getMission(mission.id));
              } catch (exc) {
                setError(exc instanceof ApiError ? exc.message : String(exc));
              }
            }}
          >
            Cancel mission
          </Button>
        )}
      </div>

      {mission.failure_reason && <ErrorNote message={mission.failure_reason} />}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Distance" value={formatDistance(mission.distance_m)} />
        <Stat label="Duration" value={formatDuration(mission.duration_s)} />
        <Stat
          label="Goal"
          value={`${mission.goal_x.toFixed(2)}, ${mission.goal_y.toFixed(2)}`}
        />
        <Stat
          label="Progress"
          value={`${mission.percent_complete.toFixed(0)}%`}
        />
      </div>

      {active && (
        <Panel title="Progress">
          <Progress percent={mission.percent_complete} />
        </Panel>
      )}

      <Panel title="Mission log">
        {mission.events.length === 0 ? (
          <Empty>No events recorded.</Empty>
        ) : (
          <ol className="space-y-1.5 font-mono text-xs">
            {mission.events.map((event) => (
              <li key={event.id} className="flex flex-wrap gap-x-3">
                <span className="tnum text-ink-dim">
                  {new Date(
                    /[zZ]|[+-]\d{2}:?\d{2}$/.test(event.created_at)
                      ? event.created_at
                      : `${event.created_at}Z`,
                  ).toLocaleTimeString()}
                </span>
                <span
                  className={`font-semibold ${LEVEL_COLOURS[event.level] ?? ""}`}
                >
                  {event.event}
                </span>
                <span className="text-ink-dim">{event.detail}</span>
              </li>
            ))}
          </ol>
        )}
      </Panel>
    </div>
  );
}
