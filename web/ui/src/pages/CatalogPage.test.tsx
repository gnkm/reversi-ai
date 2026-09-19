import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CatalogItem, GameState } from "../types.ts";
import { buildCreateGameRequest, CatalogPage } from "./CatalogPage.tsx";

const ITEMS: CatalogItem[] = [
  {
    specimen_id: "random_uniform",
    category: "random",
    display_name: "ランダム (一様)",
    description:
      "自分の手番の合法手を等確率で 1 つ選ぶ。対局中に WTHOR などの棋譜も学習済みモデルも参照しない。",
  },
  {
    specimen_id: "most_flips",
    category: "rule_based",
    display_name: "ルールベース (最多取り)",
    description: "裏返す相手石の個数が最大の合法手を選ぶ。",
  },
];

const OPENING: GameState = {
  id: "550e8400-e29b-41d4-a716-446655440000",
  board: Array.from({ length: 8 }, () =>
    Array.from({ length: 8 }, () => "empty" as const),
  ),
  side_to_move: "black",
  legal_moves: ["c4", "d3", "e6", "f5"],
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
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("buildCreateGameRequest", () => {
  it("利用者対エージェントでは選んだ石色が人間になる", () => {
    expect(
      buildCreateGameRequest({
        mode: "human_vs_agent",
        humanColor: "white",
        opponentId: "minimax",
        blackId: "ignored",
        whiteId: "ignored",
      }),
    ).toEqual({
      black: { kind: "specimen", specimen_id: "minimax" },
      white: { kind: "human" },
    });
  });

  it("エージェント対エージェントでは双方を個体で送る", () => {
    expect(
      buildCreateGameRequest({
        mode: "agent_vs_agent",
        humanColor: "black",
        opponentId: "ignored",
        blackId: "opening",
        whiteId: "opening",
      }),
    ).toEqual({
      black: { kind: "specimen", specimen_id: "opening" },
      white: { kind: "specimen", specimen_id: "opening" },
    });
  });
});

describe("CatalogPage", () => {
  it("各個体の表示名と空でない日本語の説明文を一覧する", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        expect(String(input)).toContain("/api/catalog");
        return new Response(JSON.stringify({ items: ITEMS }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );
    render(<CatalogPage onStarted={() => undefined} />);
    expect(
      await screen.findByRole("heading", { name: "ランダム (一様)" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "ルールベース (最多取り)" }),
    ).toBeTruthy();
    expect(
      screen.getByText(/自分の手番の合法手を等確率で 1 つ選ぶ/),
    ).toBeTruthy();
    expect(
      screen.getByText(/裏返す相手石の個数が最大の合法手を選ぶ/),
    ).toBeTruthy();
    expect(screen.getByText("利用者対エージェント")).toBeTruthy();
    expect(screen.getByText("エージェント対エージェント")).toBeTruthy();
  });

  it("開始すると対局状態を親へ渡す", async () => {
    const started: GameState[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/catalog")) {
          return new Response(JSON.stringify({ items: ITEMS }), {
            status: 200,
          });
        }
        expect(url.endsWith("/api/games")).toBe(true);
        expect(init?.method).toBe("POST");
        const body = JSON.parse(String(init?.body)) as unknown;
        expect(body).toEqual({
          black: { kind: "human" },
          white: { kind: "specimen", specimen_id: "random_uniform" },
        });
        return new Response(JSON.stringify(OPENING), { status: 201 });
      }),
    );
    render(<CatalogPage onStarted={(game) => started.push(game)} />);
    await screen.findByRole("heading", { name: "ランダム (一様)" });
    fireEvent.click(screen.getByRole("button", { name: "対局を開始" }));
    await waitFor(() => expect(started).toEqual([OPENING]));
  });
});
