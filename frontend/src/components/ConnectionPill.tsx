"use client";

/**
 * Shows whether the backend can reach ROS.
 *
 * Worth its own header slot: without it, a disconnected rosbridge looks
 * exactly like a fleet where every robot happens to be switched off, and
 * people waste time debugging the robot instead of the connection.
 */

import { useState } from "react";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/useLive";
import type { RosStatus } from "@/lib/types";

export function ConnectionPill() {
  const [status, setStatus] = useState<RosStatus | null>(null);
  const [reachable, setReachable] = useState(true);

  usePoll(async () => {
    try {
      setStatus(await api.rosStatus());
      setReachable(true);
    } catch {
      setReachable(false);
    }
  }, 5000);

  const { label, colour, title } = !reachable
    ? {
        label: "BACKEND DOWN",
        colour: "text-bad",
        title: "The FastAPI backend is not responding",
      }
    : status?.connected
      ? {
          label: "ROS CONNECTED",
          colour: "text-ok",
          title: `rosbridge at ${status.host}:${status.port}`,
        }
      : {
          label: "ROS OFFLINE",
          colour: "text-warn",
          title:
            status?.detail ||
            `No rosbridge at ${status?.host ?? "?"}:${status?.port ?? "?"}`,
        };

  return (
    <span
      title={title}
      className={`inline-flex items-center gap-2 rounded border border-edge bg-panel-2 px-2.5 py-1 text-[11px] font-semibold tracking-wider ${colour}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {label}
    </span>
  );
}
