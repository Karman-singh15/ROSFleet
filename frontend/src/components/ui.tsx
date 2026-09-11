"use client";

import Link from "next/link";
import type { MissionStatus, RobotStatus } from "@/lib/types";

/** A titled panel. Every page is built out of these. */
export function Panel({
  title,
  action,
  children,
  className = "",
}: {
  title?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-lg border border-edge bg-panel ${className}`}
    >
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-edge px-4 py-2.5">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-ink-dim">
            {title}
          </h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const ROBOT_COLOURS: Record<RobotStatus, string> = {
  OFFLINE: "bg-idle/15 text-idle ring-idle/30",
  IDLE: "bg-ok/15 text-ok ring-ok/30",
  NAVIGATING: "bg-busy/15 text-busy ring-busy/30",
  ERROR: "bg-bad/15 text-bad ring-bad/30",
  CHARGING: "bg-warn/15 text-warn ring-warn/30",
};

const MISSION_COLOURS: Record<MissionStatus, string> = {
  QUEUED: "bg-warn/15 text-warn ring-warn/30",
  NAVIGATING: "bg-busy/15 text-busy ring-busy/30",
  SUCCEEDED: "bg-ok/15 text-ok ring-ok/30",
  FAILED: "bg-bad/15 text-bad ring-bad/30",
  CANCELLED: "bg-idle/15 text-idle ring-idle/30",
};

export function StatusBadge({
  status,
  kind = "robot",
}: {
  status: RobotStatus | MissionStatus;
  kind?: "robot" | "mission";
}) {
  const palette =
    kind === "robot"
      ? ROBOT_COLOURS[status as RobotStatus]
      : MISSION_COLOURS[status as MissionStatus];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider ring-1 ${palette ?? ""}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}

export function Battery({ percent }: { percent: number | null }) {
  if (percent === null || !Number.isFinite(percent)) {
    return <span className="text-sm text-ink-dim">—</span>;
  }
  const level = Math.max(0, Math.min(100, percent));
  // Colour by how worried you should be, not by a gradient: a robot at 15%
  // needs to read as a problem at a glance.
  const colour =
    level > 50
      ? "bg-ok"
      : level > 20
        ? "bg-warn"
        : "bg-bad";
  return (
    <span className="inline-flex items-center gap-2">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-panel-2">
        <span
          className={`block h-full rounded-full transition-all ${colour}`}
          style={{ width: `${level}%` }}
        />
      </span>
      <span className="tnum text-sm text-ink-dim">
        {level.toFixed(0)}%
      </span>
    </span>
  );
}

export function Progress({ percent }: { percent: number }) {
  const value = Math.max(0, Math.min(100, percent));
  return (
    <div className="flex items-center gap-3">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-panel-2">
        <div
          className="h-full rounded-full bg-busy transition-all duration-500"
          style={{ width: `${value}%` }}
        />
      </div>
      <span className="tnum w-12 text-right text-sm text-ink-dim">
        {value.toFixed(0)}%
      </span>
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-edge bg-panel p-4">
      <div className="text-[11px] uppercase tracking-widest text-ink-dim">
        {label}
      </div>
      <div className="tnum mt-1 text-2xl font-semibold">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-ink-dim">{hint}</div>}
    </div>
  );
}

export function Button({
  children,
  variant = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "danger" | "ghost";
}) {
  const styles = {
    primary:
      "bg-busy text-surface hover:brightness-110 disabled:bg-idle",
    danger:
      "bg-bad text-surface hover:brightness-110 disabled:bg-idle",
    ghost:
      "border border-edge text-ink hover:bg-panel-2",
  }[variant];
  return (
    <button
      {...props}
      className={`rounded px-3 py-1.5 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${styles} ${props.className ?? ""}`}
    >
      {children}
    </button>
  );
}

/** Shown whenever the backend cannot be reached - with the actual reason. */
export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-bad">
      {message}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="py-8 text-center text-sm text-ink-dim">{children}</p>
  );
}

export function RobotLink({ id, children }: { id: number; children: React.ReactNode }) {
  return (
    <Link
      href={`/robots/${id}`}
      className="font-medium text-ink underline-offset-2 hover:underline"
    >
      {children}
    </Link>
  );
}
