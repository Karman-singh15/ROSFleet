"use client";

/**
 * Live camera for one robot.
 *
 * The <img> points at the BACKEND, never at the camera. The ESP32-CAM serves
 * one client at a time, so the backend holds the single upstream connection
 * and fans frames out - which is also why two open tabs do not fight.
 *
 * MJPEG in an <img> needs no JavaScript to decode and no player library; the
 * browser has done this since 1995. The JS here is only for the surrounding
 * state: whether a camera exists, whether frames are arriving, recording.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { CameraStatus, Robot } from "@/lib/types";
import { Button, ErrorNote, Panel } from "./ui";

export function CameraView({
  robot,
  missionId = null,
}: {
  robot: Robot;
  missionId?: number | null;
}) {
  const [status, setStatus] = useState<CameraStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  // Changing this remounts the <img> with a new URL, which is the only
  // reliable way to restart an MJPEG stream the browser has given up on.
  const [nonce, setNonce] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // A simulated robot has no camera: Gazebo's model carries no camera sensor.
  // Render nothing at all rather than an empty panel inviting setup that the
  // backend would refuse.
  const supported = robot.mode === "REAL";
  const configured = supported && Boolean(robot.camera_url);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.cameraStatus(robot.id));
    } catch (err) {
      // A failing status poll must not blank the video that is playing fine.
      if (err instanceof ApiError && err.status === 0) setError(err.message);
    }
  }, [robot.id]);

  useEffect(() => {
    if (!supported || !configured) return;
    void refresh();
    pollRef.current = setInterval(refresh, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [supported, configured, refresh]);

  // Stop streaming when the tab is hidden: an MJPEG connection left open in a
  // background tab keeps the camera busy for everyone else.
  useEffect(() => {
    const onVisibility = () => {
      if (document.hidden) setLive(false);
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  const start = () => {
    setLoaded(false);
    setError(null);
    setNonce((n) => n + 1);
    setLive(true);
  };

  const toggleRecording = async () => {
    setBusy(true);
    setError(null);
    try {
      if (status?.recording_id) {
        await api.stopRecording(robot.id);
      } else {
        // Recording taps the same feed, so make sure it is flowing.
        if (!live) start();
        await api.startRecording(robot.id, missionId);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!supported) return null;

  if (!configured) {
    return (
      <Panel title="Camera">
        <p className="text-sm text-ink-dim">
          No camera on this robot. Set its stream URL to enable live view —
          for an ESP32-CAM that is{" "}
          <code className="rounded bg-panel-2 px-1 py-0.5 text-xs">
            http://&lt;camera-ip&gt;:81/stream
          </code>
          .
        </p>
        <CameraUrlForm robot={robot} />
      </Panel>
    );
  }

  const recording = Boolean(status?.recording_id);

  return (
    <Panel
      title="Camera"
      action={
        <div className="flex items-center gap-2">
          {recording && (
            <span className="flex items-center gap-1.5 text-xs font-semibold text-bad">
              <span className="h-2 w-2 animate-pulse rounded-full bg-bad" />
              REC
            </span>
          )}
          <Button
            variant="ghost"
            onClick={toggleRecording}
            disabled={busy}
            aria-label={recording ? "Stop recording" : "Start recording"}
          >
            {recording ? "Stop recording" : "Record"}
          </Button>
        </div>
      }
    >
      <div className="relative aspect-[4/3] w-full overflow-hidden rounded bg-panel-2">
        {live ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              key={nonce}
              src={api.cameraStreamUrl(robot.id, nonce)}
              alt={`Live view from ${robot.name}`}
              className="h-full w-full object-contain"
              onLoad={() => setLoaded(true)}
              onError={() => {
                setLive(false);
                setError(
                  "The stream stopped. The camera may be off, out of range, " +
                    "or busy with another client.",
                );
              }}
            />
            {!loaded && (
              <div className="absolute inset-0 grid place-items-center text-sm text-ink-dim">
                Connecting to the camera…
              </div>
            )}
          </>
        ) : (
          <div className="absolute inset-0 grid place-items-center gap-3">
            <Button onClick={start}>Start live view</Button>
          </div>
        )}
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-ink-dim sm:grid-cols-4">
        <CameraFact label="Viewers" value={String(status?.viewers ?? 0)} />
        <CameraFact
          label="Last frame"
          value={
            status?.last_frame_age_seconds == null
              ? "—"
              : `${status.last_frame_age_seconds.toFixed(1)} s ago`
          }
        />
        <CameraFact
          label="Feed"
          value={status?.stale ? "stale" : status?.streaming ? "live" : "idle"}
        />
        <CameraFact
          label="Recording"
          value={status?.recording_id ? "on" : "off"}
        />
      </dl>

      {(error || status?.error) && (
        <div className="mt-3">
          <ErrorNote message={error ?? status?.error ?? ""} />
        </div>
      )}
    </Panel>
  );
}

function CameraFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="uppercase tracking-wider">{label}</dt>
      <dd className="tnum text-ink">{value}</dd>
    </div>
  );
}

/** Set or clear a robot's camera URL without leaving the page. */
function CameraUrlForm({ robot }: { robot: Robot }) {
  const [value, setValue] = useState(robot.camera_url ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.updateRobot(robot.id, { camera_url: value.trim() });
      // The robot object is server state owned by the page above; a reload
      // is honest here and avoids two sources of truth for one field.
      window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSaving(false);
    }
  };

  return (
    <form onSubmit={save} className="mt-3 flex flex-wrap gap-2">
      <label htmlFor={`camera-url-${robot.id}`} className="sr-only">
        Camera stream URL
      </label>
      <input
        id={`camera-url-${robot.id}`}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="http://192.168.1.51:81/stream"
        className="min-w-0 flex-1 rounded border border-edge bg-panel-2 px-3 py-1.5 text-sm text-ink placeholder:text-ink-dim"
      />
      <Button type="submit" disabled={saving}>
        {saving ? "Saving…" : "Save"}
      </Button>
      {error && (
        <div className="w-full">
          <ErrorNote message={error} />
        </div>
      )}
    </form>
  );
}
