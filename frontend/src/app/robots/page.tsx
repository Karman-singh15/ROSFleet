"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { formatAgo } from "@/lib/format";
import { usePoll } from "@/lib/useLive";
import type { Robot } from "@/lib/types";
import {
  Battery,
  Button,
  Empty,
  ErrorNote,
  Panel,
  RobotLink,
  StatusBadge,
} from "@/components/ui";

export default function RobotsPage() {
  const [robots, setRobots] = useState<Robot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  usePoll(async () => {
    try {
      setRobots(await api.listRobots());
      setError(null);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    }
  }, 4000);

  const addRobot = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await api.createRobot({
        code: code.trim(),
        name: name.trim() || code.trim(),
      });
      setCode("");
      setName("");
      setRobots(await api.listRobots());
      setError(null);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const field =
    "mt-1 block rounded border border-edge bg-panel-2 px-2 py-1.5 text-sm text-ink outline-none focus:border-busy";

  return (
    <div className="space-y-6">
      {error && <ErrorNote message={error} />}

      <Panel title="Fleet">
        {robots.length === 0 ? (
          <Empty>No robots registered.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-[11px] uppercase tracking-widest text-ink-dim">
                <tr>
                  <th className="pb-2 font-medium">Code</th>
                  <th className="pb-2 font-medium">Name</th>
                  <th className="pb-2 font-medium">Mode</th>
                  <th className="pb-2 font-medium">Status</th>
                  <th className="pb-2 font-medium">Battery</th>
                  <th className="pb-2 font-medium">Firmware</th>
                  <th className="pb-2 font-medium">Last seen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-edge">
                {robots.map((robot) => (
                  <tr key={robot.id}>
                    <td className="py-2.5">
                      <RobotLink id={robot.id}>{robot.code}</RobotLink>
                    </td>
                    <td className="py-2.5">{robot.name}</td>
                    <td className="py-2.5 text-ink-dim">
                      {robot.mode}
                    </td>
                    <td className="py-2.5">
                      <StatusBadge status={robot.status} />
                    </td>
                    <td className="py-2.5">
                      <Battery percent={robot.battery_percent} />
                    </td>
                    <td className="py-2.5 text-ink-dim">
                      {robot.firmware_version ?? "—"}
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

      <Panel title="Register a robot">
        <form onSubmit={addRobot} className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-ink-dim">
            Code
            <input
              value={code}
              onChange={(event) => setCode(event.target.value)}
              required
              placeholder="RB002"
              className={`${field} w-32`}
            />
          </label>
          <label className="text-xs text-ink-dim">
            Name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Delivery Robot"
              className={`${field} w-56`}
            />
          </label>
          <Button type="submit" disabled={busy || !code.trim()}>
            {busy ? "Adding…" : "Add robot"}
          </Button>
        </form>
      </Panel>
    </div>
  );
}
