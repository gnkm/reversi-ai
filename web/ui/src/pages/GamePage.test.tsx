import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Cell, GameState } from "../types.ts";
import { GamePage } from "./GamePage.tsx";

function emptyBoard(): Cell[][] {
  return Array.from({ length: 8 }, () =>
    Array.from({ length: 8 }, () => "empty" as const),
  );
}

function game(overrides: Partial<GameState> = {}): GameState {
  return {
    id: "550e8400-e29b-41d4-a716-446655440000",
    board: emptyBoard(),
    side_to_move: "black",
    legal_moves: ["c4"],
    pass_is_legal: false,
    last_move: null,
    is_over: false,
    official_score: { black: 2, white: 2 },
    result: null,
    status: "in_progress",
    continuation_possible: true,
    unplayable_reason: null,
    black: { kind: "human" },
    white: { kind: "specimen", specimen_id: "random_uniform" },
    ...overrides,
  };
}

const names = new Map([["random_uniform", "ランダム (一様)"]]);

describe("GamePage", () => {
  it("盤面画面でカタログ一覧を相手選択に使わない", () => {
    render(
      <GamePage
        game={game()}
        specimenNames={names}
        onGame={() => undefined}
        onBack={() => undefined}
      />,
    );
    expect(screen.getByRole("heading", { name: "盤面" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "カタログ" })).toBeNull();
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.queryByLabelText("対戦相手")).toBeNull();
    expect(screen.getByText(/あなたの入力待ちです/)).toBeTruthy();
  });

  it("終局後にカタログ画面へ戻れる", () => {
    const backs: string[] = [];
    render(
      <GamePage
        game={game({
          is_over: true,
          status: "completed",
          continuation_possible: false,
          legal_moves: [],
          result: { winner: "black", black: "win", white: "loss" },
          official_score: { black: 40, white: 24 },
        })}
        specimenNames={names}
        onGame={() => undefined}
        onBack={() => backs.push("back")}
      />,
    );
    expect(screen.getByText("黒の勝ちです。")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "カタログへ戻る" }));
    expect(backs).toEqual(["back"]);
  });
});
