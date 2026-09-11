"use client";

/** Fleet analytics. Every number here is computed from the missions table. */

import { api, ApiError } from "@/lib/api";
import { formatDistance, formatDuration } from "@/lib/format";
import { useAsync } from "@/lib/useLive";
import type { Analytics } from "@/lib/types";
import { Empty, ErrorNote, Panel, Stat } from "@/components/ui";

function Bar({
  label,
  value,
  max,
  colour = "bg-busy",
}: {
  label: string;
  value: number;
  max: number;
  colour?: string;
}) {
  const width = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-40 shrink-0 truncate text-ink-dim">
        {label}
      </span>
      <span className="h-2 flex-1 overflow-hidden rounded-full bg-panel-2">
        <span
          className={`block h-full rounded-full ${colour}`}
          style={{ width: `${width}%` }}
        />
      </span>
      <span className="tnum w-12 text-right">{value}</span>
    </div>
  );
}

export default function AnalyticsPage() {
  const { data, error } = useAsync<Analytics>(() => api.analytics());

  if (error) return <ErrorNote message={error} />;
  if (!data) return <Empty>Loading…</Empty>;

  const { counts } = data;
  const maxFailure = Math.max(1, ...data.failures.map((row) => row.count));
  const maxDestination = Math.max(
    1,
    ...data.busiest_destinations.map((row) => row.count),
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat
          label="Success rate"
          value={`${counts.success_rate.toFixed(0)}%`}
          hint={`${counts.succeeded} of ${
            counts.succeeded + counts.failed + counts.cancelled
          } finished`}
        />
        <Stat
          label="Average mission"
          value={formatDuration(data.average_duration_s)}
          hint="successful missions only"
        />
        <Stat
          label="Total distance"
          value={formatDistance(data.total_distance_m)}
          hint="all missions"
        />
        <Stat label="Missions" value={counts.total} hint={`${counts.active} active`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Outcomes">
          <div className="space-y-2">
            <Bar
              label="Succeeded"
              value={counts.succeeded}
              max={Math.max(1, counts.total)}
              colour="bg-ok"
            />
            <Bar
              label="Failed"
              value={counts.failed}
              max={Math.max(1, counts.total)}
              colour="bg-bad"
            />
            <Bar
              label="Cancelled"
              value={counts.cancelled}
              max={Math.max(1, counts.total)}
              colour="bg-idle"
            />
            <Bar
              label="Active"
              value={counts.active}
              max={Math.max(1, counts.total)}
            />
          </div>
        </Panel>

        <Panel title="Why missions failed">
          {data.failures.length === 0 ? (
            <Empty>No failures recorded.</Empty>
          ) : (
            <div className="space-y-2">
              {data.failures.map((row) => (
                <Bar
                  key={row.reason}
                  label={row.reason}
                  value={row.count}
                  max={maxFailure}
                  colour="bg-bad"
                />
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Robot utilisation">
          {data.robots.length === 0 ? (
            <Empty>No robots.</Empty>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-[11px] uppercase tracking-widest text-ink-dim">
                <tr>
                  <th className="pb-2 font-medium">Robot</th>
                  <th className="pb-2 font-medium">Missions</th>
                  <th className="pb-2 font-medium">Distance</th>
                  <th className="pb-2 font-medium">Success</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-edge">
                {data.robots.map((row) => (
                  <tr key={row.robot_id}>
                    <td className="py-2">{row.robot_code}</td>
                    <td className="tnum py-2">{row.missions}</td>
                    <td className="tnum py-2">
                      {formatDistance(row.total_distance_m)}
                    </td>
                    <td className="tnum py-2">
                      {row.success_rate.toFixed(0)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel title="Busiest destinations">
          {data.busiest_destinations.length === 0 ? (
            <Empty>No missions yet.</Empty>
          ) : (
            <div className="space-y-2">
              {data.busiest_destinations.map((row) => (
                <Bar
                  key={row.destination}
                  label={row.destination}
                  value={row.count}
                  max={maxDestination}
                  colour="bg-warn"
                />
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
