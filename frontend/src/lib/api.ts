/**
 * The ONLY place the frontend talks to the network.
 *
 * Note what is absent: any mention of ROS, topics, /cmd_vel or poses beyond
 * plain numbers. The browser asks the backend to do things in the
 * application's own vocabulary, and the backend deals with the robotics.
 */

import type {
  Analytics,
  CameraStatus,
  Destination,
  Mission,
  MissionDetail,
  RecordingSummary,
  Robot,
  RobotMap,
  RosStatus,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws";

/** Thrown with the backend's own message, so the UI can show the real reason. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      ...init,
    });
  } catch {
    // fetch() rejects identically for "nothing is listening" and "the
    // response was blocked by CORS", and the browser deliberately hides
    // which. Name both, because during development it is always one of them
    // and the fix is completely different.
    throw new ApiError(
      `Cannot reach the backend at ${API_URL}. Either it is not running, ` +
        `or it is not allowing requests from ${
          typeof window === "undefined" ? "this origin" : window.location.origin
        } (set CORS_ORIGINS on the backend).`,
      0,
    );
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* the body was not JSON; keep the status line */
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  rosStatus: () => request<RosStatus>("/api/ros/status"),

  listRobots: () => request<Robot[]>("/api/robots"),
  getRobot: (id: number) => request<Robot>(`/api/robots/${id}`),
  createRobot: (body: { code: string; name: string; mode?: string }) =>
    request<Robot>("/api/robots", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listMaps: () => request<RobotMap[]>("/api/maps"),
  listDestinations: () => request<Destination[]>("/api/destinations"),
  listMapDestinations: (mapId: number) =>
    request<Destination[]>(`/api/maps/${mapId}/destinations`),
  createDestination: (body: {
    map_id: number;
    name: string;
    x: number;
    y: number;
    yaw?: number;
    description?: string | null;
  }) =>
    request<Destination>("/api/destinations", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteDestination: (id: number) =>
    request<void>(`/api/destinations/${id}`, { method: "DELETE" }),

  listMissions: (params?: { robot_id?: number; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.robot_id) query.set("robot_id", String(params.robot_id));
    if (params?.limit) query.set("limit", String(params.limit));
    const suffix = query.toString() ? `?${query}` : "";
    return request<Mission[]>(`/api/missions${suffix}`);
  },
  getMission: (id: number) => request<MissionDetail>(`/api/missions/${id}`),
  createMission: (body: {
    robot_id: number;
    destination_id?: number;
    goal_x?: number;
    goal_y?: number;
    goal_yaw?: number;
    preempt?: boolean;
  }) =>
    request<Mission>("/api/missions", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  cancelMission: (id: number) =>
    request<Mission>(`/api/missions/${id}/cancel`, { method: "POST" }),

  analytics: () => request<Analytics>("/api/analytics"),

  /** Absolute URL of a map's image, for <img src>. */
  mapImageUrl: (mapId: number) => `${API_URL}/api/maps/${mapId}/image`,

  // ------------------------------------------------------------- camera
  updateRobot: (id: number, body: { name?: string; camera_url?: string }) =>
    request<Robot>(`/api/robots/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  cameraStatus: (robotId: number) =>
    request<CameraStatus>(`/api/robots/${robotId}/camera`),

  /**
   * The MJPEG stream, for <img src>. Note this points at the BACKEND, never
   * at the camera: the ESP32-CAM serves one client at a time, so the backend
   * holds the single connection and fans frames out to every viewer.
   *
   * The cache-buster matters - without it a browser reuses the previous
   * stream's connection and the image stays frozen after a remount.
   */
  cameraStreamUrl: (robotId: number, nonce: number | string = "") =>
    `${API_URL}/api/robots/${robotId}/camera/stream${nonce ? `?t=${nonce}` : ""}`,

  cameraSnapshotUrl: (robotId: number, nonce: number | string = "") =>
    `${API_URL}/api/robots/${robotId}/camera/snapshot${nonce ? `?t=${nonce}` : ""}`,

  startRecording: (robotId: number, missionId?: number | null) =>
    request<RecordingSummary>(`/api/robots/${robotId}/camera/recording`, {
      method: "POST",
      body: JSON.stringify({ mission_id: missionId ?? null }),
    }),
  stopRecording: (robotId: number) =>
    request<RecordingSummary>(`/api/robots/${robotId}/camera/recording`, {
      method: "DELETE",
    }),
  listRecordings: (params?: { robot_id?: number; mission_id?: number }) => {
    const query = new URLSearchParams();
    if (params?.robot_id) query.set("robot_id", String(params.robot_id));
    if (params?.mission_id) query.set("mission_id", String(params.mission_id));
    const suffix = query.toString() ? `?${query}` : "";
    return request<RecordingSummary[]>(`/api/recordings${suffix}`);
  },
  recordingFrameUrl: (recordingId: string, index: number) =>
    `${API_URL}/api/recordings/${recordingId}/frames/${index}`,
};
