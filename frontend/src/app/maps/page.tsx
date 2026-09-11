"use client";

/**
 * Maps page. The click-to-place-a-destination feature lives here: rather
 * than asking someone to type x = 3.71, y = -1.82, they click the spot on
 * the floor plan and name it.
 */

import { useCallback, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { usePoll } from "@/lib/useLive";
import type { Destination, RobotMap, Robot } from "@/lib/types";
import { MapView, type MapClick } from "@/components/MapView";
import { Button, Empty, ErrorNote, Panel } from "@/components/ui";

export default function MapsPage() {
  const [maps, setMaps] = useState<RobotMap[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [destinations, setDestinations] = useState<Destination[]>([]);
  const [robots, setRobots] = useState<Robot[]>([]);
  const [pending, setPending] = useState<MapClick | null>(null);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const selected = maps.find((item) => item.id === selectedId) ?? null;

  const reload = useCallback(async () => {
    try {
      const nextMaps = await api.listMaps();
      setMaps(nextMaps);
      const activeId = selectedId ?? nextMaps[0]?.id ?? null;
      if (activeId !== selectedId) setSelectedId(activeId);
      if (activeId !== null) {
        setDestinations(await api.listMapDestinations(activeId));
      }
      setRobots(await api.listRobots());
      setError(null);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    }
  }, [selectedId]);

  usePoll(reload, 3000);

  const saveDestination = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!pending || !selected || !newName.trim()) return;
    try {
      await api.createDestination({
        map_id: selected.id,
        name: newName.trim(),
        x: Number(pending.x.toFixed(3)),
        y: Number(pending.y.toFixed(3)),
      });
      setPending(null);
      setNewName("");
      setDestinations(await api.listMapDestinations(selected.id));
      setError(null);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    }
  };

  const remove = async (id: number) => {
    try {
      await api.deleteDestination(id);
      if (selected) setDestinations(await api.listMapDestinations(selected.id));
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    }
  };

  return (
    <div className="space-y-6">
      {error && <ErrorNote message={error} />}

      {maps.length === 0 ? (
        <Panel title="Maps">
          <Empty>
            No maps yet. Generate the simulated one with{" "}
            <code>python3 scripts/generate_sim_map.py</code>, then seed it with{" "}
            <code>python3 backend/seed.py</code> — or upload a real one saved
            by <code>map_server map_saver</code>.
          </Empty>
        </Panel>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
          <Panel
            title={selected?.name ?? "Map"}
            action={
              maps.length > 1 ? (
                <select
                  value={selectedId ?? ""}
                  onChange={(event) => setSelectedId(Number(event.target.value))}
                  className="rounded border border-edge bg-panel-2 px-2 py-1 text-xs text-ink"
                >
                  {maps.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              ) : null
            }
          >
            {selected && (
              <MapView
                map={selected}
                destinations={destinations}
                robots={robots}
                pending={pending}
                onPick={setPending}
              />
            )}
            <p className="mt-2 text-xs text-ink-dim">
              Click anywhere on the map to place a destination.
            </p>
          </Panel>

          <div className="space-y-6">
            <Panel title="New destination">
              {pending ? (
                <form onSubmit={saveDestination} className="space-y-3">
                  <p className="tnum text-sm text-ink-dim">
                    {pending.x.toFixed(2)}, {pending.y.toFixed(2)} m
                  </p>
                  <input
                    autoFocus
                    value={newName}
                    onChange={(event) => setNewName(event.target.value)}
                    placeholder="AI Lab"
                    className="w-full rounded border border-edge bg-panel-2 px-2 py-1.5 text-sm text-ink outline-none focus:border-busy"
                  />
                  <div className="flex gap-2">
                    <Button type="submit" disabled={!newName.trim()}>
                      Save
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => {
                        setPending(null);
                        setNewName("");
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </form>
              ) : (
                <Empty>Click the map to choose a spot.</Empty>
              )}
            </Panel>

            <Panel title={`Destinations (${destinations.length})`}>
              {destinations.length === 0 ? (
                <Empty>None yet.</Empty>
              ) : (
                <ul className="divide-y divide-edge text-sm">
                  {destinations.map((destination) => (
                    <li
                      key={destination.id}
                      className="flex items-center gap-2 py-2"
                    >
                      <span className="h-2 w-2 rounded-full bg-warn" />
                      <span className="font-medium">{destination.name}</span>
                      <span className="tnum text-xs text-ink-dim">
                        {destination.x.toFixed(2)}, {destination.y.toFixed(2)}
                      </span>
                      <button
                        onClick={() => remove(destination.id)}
                        className="ml-auto text-xs text-ink-dim hover:text-bad"
                      >
                        remove
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}
