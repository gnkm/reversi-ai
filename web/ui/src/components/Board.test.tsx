import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Cell } from "../types.ts";
import { Board, FILES, RANKS_TOP_DOWN } from "./Board.tsx";

function openingBoard(): Cell[][] {
  const board = Array.from({ length: 8 }, () =>
    Array.from({ length: 8 }, () => "empty" as const),
  );
  board[3][3] = "white";
  board[3][4] = "black";
  board[4][3] = "black";
  board[4][4] = "white";
  return board;
}

describe("Board", () => {
  it("8×8 と a–h / 1–8 を出し、a1 は黒から見て左下にする", () => {
    const { container } = render(
      <Board
        board={openingBoard()}
        legalMoves={["c4", "d3", "e6", "f5"]}
        lastMove={null}
        showLegal={false}
      />,
    );
    const squares = [...container.querySelectorAll("[data-square]")];
    expect(squares).toHaveLength(64);
    expect(squares[0].getAttribute("data-square")).toBe("a8");
    expect(squares[7].getAttribute("data-square")).toBe("h8");
    expect(squares[56].getAttribute("data-square")).toBe("a1");
    expect(squares[63].getAttribute("data-square")).toBe("h1");
    for (const file of FILES) {
      expect(screen.getAllByText(file).length).toBeGreaterThan(0);
    }
    for (const rank of RANKS_TOP_DOWN) {
      expect(screen.getAllByText(String(rank)).length).toBeGreaterThan(0);
    }
  });

  it("利用者手番に合法手の印と直前着手の印を出す", () => {
    render(
      <Board
        board={openingBoard()}
        legalMoves={["c4"]}
        lastMove={{ type: "place", square: "d3" }}
        showLegal={true}
        onPlace={() => undefined}
      />,
    );
    expect(screen.getByRole("button", { name: /c4 .*合法手/ })).toBeTruthy();
    const last = document.querySelector('[data-square="d3"]');
    expect(last?.className).toContain("square-last");
    expect(last?.querySelector(".last-mark")).not.toBeNull();
    expect(
      document.querySelector('[data-square="c4"] .legal-mark'),
    ).not.toBeNull();
    expect(document.querySelector('[data-square="a1"] .legal-mark')).toBeNull();
  });
});
