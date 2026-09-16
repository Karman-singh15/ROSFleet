/**
 * Types mirroring the backend's Pydantic schemas.
 *
 * Kept by hand rather than generated, because the API surface is small and a
 * codegen step is one more thing to keep running. If the API grows, generate
 * these from /openapi.json instead.
 */

export type RobotStatus =
  | "OFFLINE"
  | "IDLE"
  | "NAVIGATING"
  | "ERROR"
  | "CHARGING";

export type RobotMode = "REAL" | "SIMULATED";

export interface Robot {
  id: number;
  code: string;
  name: string;
  status: RobotStatus;
  mode: RobotMode;
  battery_percent: number | null;
  battery_voltage: number | null;
  x: number | null;
  y: number | null;
  yaw: number | null;
  linear_velocity: number | null;
  camera_url: string | null;
  firmware_version: string | null;
  last_error: string | null;
  last_seen: string | null;
  created_at: string;
}

export interface CameraStatus {
  robot_id: number;
  supported: boolean;
  configured: boolean;
  streaming: boolean;
  viewers: number;
  last_frame_age_seconds: number | null;
  stale: boolean;
  error: string | null;
  recording_id: string | null;
}

export interface RecordingSummary {
  recording_id: string;
  robot_id: number;
  mission_id: number | null;
  started_at: number;
  stopped_at: number | null;
  duration_seconds: number;
  frame_count: number;
  total_bytes: number;
  max_fps: number;
}

export interface RobotMap {
  id: number;
  name: string;
  description: string | null;
  resolution: number;
  origin_x: number;
  origin_y: number;
  origin_yaw: number;
  width_px: number;
  height_px: number;
  created_at: string;
}

export interface Destination {
  id: number;
  map_id: number;
  name: string;
  description: string | null;
  x: number;
  y: number;
  yaw: number;
  created_at: string;
}

export type MissionStatus =
  | "QUEUED"
  | "NAVIGATING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED";

export interface Mission {
  id: number;
  robot_id: number;
  destination_id: number | null;
  destination_name: string;
  goal_x: number;
  goal_y: number;
  goal_yaw: number;
  status: MissionStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  distance_m: number;
  duration_s: number;
  percent_complete: number;
  failure_reason: string | null;
}

export interface MissionEvent {
  id: number;
  level: string;
  event: string;
  detail: string;
  created_at: string;
}

export interface MissionDetail extends Mission {
  events: MissionEvent[];
}

export interface Analytics {
  counts: {
    total: number;
    succeeded: number;
    failed: number;
    cancelled: number;
    active: number;
    success_rate: number;
  };
  average_duration_s: number;
  average_distance_m: number;
  total_distance_m: number;
  robots: {
    robot_id: number;
    robot_code: string;
    missions: number;
    total_distance_m: number;
    total_duration_s: number;
    navigating_seconds: number;
    success_rate: number;
  }[];
  failures: { reason: string; count: number }[];
  busiest_destinations: { destination: string; count: number }[];
}

export interface RosStatus {
  connected: boolean;
  host: string;
  port: number;
  detail: string;
}

/** Messages pushed down the /ws WebSocket. */
export type LiveMessage =
  | { type: "hello"; data: { clients: number } }
  | {
      type: "robot_update";
      data: {
        id: number;
        code: string;
        status: RobotStatus;
        battery_percent: number | null;
        x: number | null;
        y: number | null;
        last_error: string | null;
      };
    }
  | {
      type: "mission_update";
      data: {
        id: number;
        robot_id: number;
        status: MissionStatus;
        percent_complete: number;
        distance_m: number;
        duration_s: number;
        destination_name: string;
      };
    }
  | {
      type: "mission_event";
      data: {
        mission_id: number;
        level: string;
        event: string;
        detail: string;
      };
    };
