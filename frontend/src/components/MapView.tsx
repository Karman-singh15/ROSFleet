"use client";

/**
 * The map, with destinations and live robot positions drawn on top.
 *
 * THE COORDINATE PROBLEM, which is the whole substance of this component:
 *
 *   ROS map frame            image pixels
 *   +Y up, metres            +row DOWN, pixels
 *   origin at a world point  origin top-left
 *
 * so converting between them needs a scale AND a row flip:
 *
 *   col = (x - origin_x) / resolution
 *   row = height_px - (y - origin_y) / resolution
 *
 * Getting the flip wrong produces a map where everything is mirrored
 * vertically, which is surprisingly easy to not notice until the robot
 * drives the wrong way.
 */

import { useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Destination, RobotMap, Robot } from "@/lib/types";

export interface MapClick {
  x: number;
  y: number;
}

export function worldToPixel(map: RobotMap, x: number, y: number) {
  return {
    col: (x - map.origin_x) / map.resolution,
    row: map.height_px - (y - map.origin_y) / map.resolution,
  };
}

export function pixelToWorld(map: RobotMap, col: number, row: number) {
  return {
    x: map.origin_x + col * map.resolution,
    y: map.origin_y + (map.height_px - row) * map.resolution,
  };
}

export function MapView({
  map,
  destinations,
  robots = [],
  onPick,
  pending,
}: {
  map: RobotMap;
  destinations: Destination[];
  robots?: Robot[];
  onPick?: (point: MapClick) => void;
  pending?: MapClick | null;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<MapClick | null>(null);

  /** Translate a DOM click into map-frame metres. */
  const toWorld = (event: React.MouseEvent): MapClick | null => {
    const box = frame.current?.getBoundingClientRect();
    if (!box || box.width === 0) return null;
    // The image is scaled to fit, so go via a 0..1 fraction rather than
    // assuming one CSS pixel is one map pixel.
    const fx = (event.clientX - box.left) / box.width;
    const fy = (event.clientY - box.top) / box.height;
    return pixelToWorld(map, fx * map.width_px, fy * map.height_px);
  };

  return (
    <div className="space-y-2">
      <div
        ref={frame}
        onMouseMove={(event) => setHover(toWorld(event))}
        onMouseLeave={() => setHover(null)}
        onClick={(event) => {
          const point = toWorld(event);
          if (point && onPick) onPick(point);
        }}
        className={`relative w-full overflow-hidden rounded border border-edge bg-panel-2 ${
          onPick ? "cursor-crosshair" : ""
        }`}
        style={{ aspectRatio: `${map.width_px} / ${map.height_px}` }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={api.mapImageUrl(map.id)}
          alt={map.name}
          // The grid is a handful of pixels per metre; smoothing it turns
          // crisp walls into grey fog.
          className="absolute inset-0 h-full w-full select-none [image-rendering:pixelated]"
          draggable={false}
        />

        {destinations.map((destination) => {
          const { col, row } = worldToPixel(map, destination.x, destination.y);
          return (
            <div
              key={destination.id}
              className="absolute -translate-x-1/2 -translate-y-1/2"
              style={{
                left: `${(col / map.width_px) * 100}%`,
                top: `${(row / map.height_px) * 100}%`,
              }}
            >
              <div className="h-2.5 w-2.5 rounded-full bg-warn ring-2 ring-surface" />
              <div className="mt-0.5 whitespace-nowrap rounded bg-surface/85 px-1 text-[10px] font-medium text-ink">
                {destination.name}
              </div>
            </div>
          );
        })}

        {robots.map((robot) => {
          if (robot.x === null || robot.y === null) return null;
          const { col, row } = worldToPixel(map, robot.x, robot.y);
          // Screen Y grows downward, so a positive ROS yaw (counter-clockwise)
          // is a negative CSS rotation.
          const heading = -((robot.yaw ?? 0) * 180) / Math.PI;
          return (
            <div
              key={robot.id}
              className="absolute -translate-x-1/2 -translate-y-1/2"
              style={{
                left: `${(col / map.width_px) * 100}%`,
                top: `${(row / map.height_px) * 100}%`,
              }}
              title={`${robot.code} (${robot.x.toFixed(2)}, ${robot.y.toFixed(2)})`}
            >
              <div
                className="grid h-4 w-4 place-items-center rounded-full bg-busy ring-2 ring-surface transition-all duration-500"
                style={{ transform: `rotate(${heading}deg)` }}
              >
                <span className="ml-1 text-[9px] font-bold text-surface">
                  ▶
                </span>
              </div>
            </div>
          );
        })}

        {pending && (
          <div
            className="absolute -translate-x-1/2 -translate-y-1/2"
            style={{
              left: `${(worldToPixel(map, pending.x, pending.y).col / map.width_px) * 100}%`,
              top: `${(worldToPixel(map, pending.x, pending.y).row / map.height_px) * 100}%`,
            }}
          >
            <div className="h-3 w-3 animate-pulse rounded-full bg-ok ring-2 ring-surface" />
          </div>
        )}
      </div>

      <div className="flex flex-wrap justify-between gap-2 text-xs text-ink-dim">
        <span>
          {map.width_px} × {map.height_px} px · {map.resolution} m/px ·{" "}
          {(map.width_px * map.resolution).toFixed(1)} ×{" "}
          {(map.height_px * map.resolution).toFixed(1)} m
        </span>
        <span className="tnum">
          {hover ? `${hover.x.toFixed(2)}, ${hover.y.toFixed(2)} m` : " "}
        </span>
      </div>
    </div>
  );
}
