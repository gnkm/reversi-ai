export const DEFAULT_AGENT_MOVE_INTERVAL_SECONDS = 1;
export const DEFAULT_AGENT_MOVE_INTERVAL_MS = 1000;
export const MIN_AGENT_MOVE_INTERVAL_SECONDS = 0;
export const MAX_AGENT_MOVE_INTERVAL_SECONDS = 60;

export function parseMoveIntervalSeconds(raw: string): number {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return DEFAULT_AGENT_MOVE_INTERVAL_SECONDS;
  }
  const n = Number(trimmed);
  if (!Number.isFinite(n)) {
    return DEFAULT_AGENT_MOVE_INTERVAL_SECONDS;
  }
  return Math.min(
    MAX_AGENT_MOVE_INTERVAL_SECONDS,
    Math.max(MIN_AGENT_MOVE_INTERVAL_SECONDS, n),
  );
}

export function moveIntervalMsFromSeconds(seconds: number): number {
  return Math.round(parseMoveIntervalSeconds(String(seconds)) * 1000);
}
