/** Small formatting helpers shared across the pages. */

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0s";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  if (minutes === 0) return `${remainder}s`;
  if (minutes < 60) return `${minutes}m ${remainder}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function formatDistance(metres: number): string {
  if (!Number.isFinite(metres)) return "—";
  return metres >= 1000
    ? `${(metres / 1000).toFixed(2)} km`
    : `${metres.toFixed(1)} m`;
}

/** "4s ago", "2m ago" - null means never seen. */
export function formatAgo(iso: string | null): string {
  if (!iso) return "never";
  // The API returns UTC; a bare timestamp with no zone is parsed as local
  // time by Date, which would show a robot as hours stale.
  const stamp = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const seconds = (Date.now() - new Date(stamp).getTime()) / 1000;
  if (!Number.isFinite(seconds)) return "unknown";
  if (seconds < 0) return "just now";
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function degrees(radians: number | null): string {
  if (radians === null || !Number.isFinite(radians)) return "—";
  return `${((radians * 180) / Math.PI).toFixed(0)}°`;
}
