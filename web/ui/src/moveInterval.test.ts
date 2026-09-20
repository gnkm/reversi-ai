import { describe, expect, it } from "vitest";
import {
  DEFAULT_AGENT_MOVE_INTERVAL_MS,
  DEFAULT_AGENT_MOVE_INTERVAL_SECONDS,
  moveIntervalMsFromSeconds,
  parseMoveIntervalSeconds,
} from "./moveInterval.ts";

describe("着手間隔", () => {
  it("未変更時の間隔は 1 秒である", () => {
    expect(DEFAULT_AGENT_MOVE_INTERVAL_SECONDS).toBe(1);
    expect(DEFAULT_AGENT_MOVE_INTERVAL_MS).toBe(1000);
    expect(parseMoveIntervalSeconds("")).toBe(1);
    expect(moveIntervalMsFromSeconds(1)).toBe(1000);
  });

  it("空や非数は未設定として 1 秒に戻す", () => {
    expect(parseMoveIntervalSeconds("   ")).toBe(1);
    expect(parseMoveIntervalSeconds("abc")).toBe(1);
  });
});
