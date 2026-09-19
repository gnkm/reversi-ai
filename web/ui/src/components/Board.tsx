import type { Cell, Move } from "../types.ts";

export const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"] as const;
export const RANKS_TOP_DOWN = [8, 7, 6, 5, 4, 3, 2, 1] as const;

export function algebraic(fileIndex: number, rank: number): string {
  return `${FILES[fileIndex]}${rank}`;
}

export function lastPlacedSquare(lastMove: Move | null): string | null {
  if (lastMove === null || lastMove.type !== "place") {
    return null;
  }
  return lastMove.square;
}

type BoardProps = {
  board: Cell[][];
  legalMoves: readonly string[];
  lastMove: Move | null;
  showLegal: boolean;
  onPlace?: (square: string) => void;
};

type SquareProps = {
  square: string;
  cell: Cell;
  legal: boolean;
  last: boolean;
  showLegal: boolean;
  onPlace?: (square: string) => void;
};

function FileLabels({ prefix }: { prefix: string }) {
  return (
    <>
      <span className="board-corner" />
      {FILES.map((file) => (
        <span key={`${prefix}-${file}`} className="board-file">
          {file}
        </span>
      ))}
      <span className="board-corner" />
    </>
  );
}

function SquareView({
  square,
  cell,
  legal,
  last,
  showLegal,
  onPlace,
}: SquareProps) {
  const markLegal = showLegal && legal;
  const className = [
    "square",
    `square-${cell}`,
    markLegal ? "square-legal" : "",
    last ? "square-last" : "",
  ]
    .filter((part) => part !== "")
    .join(" ");
  const canPlace = markLegal && onPlace !== undefined;
  const label = squareLabel(square, cell, markLegal, last);
  const marks = (
    <>
      {cell !== "empty" ? (
        <span className={`stone stone-${cell}`} aria-hidden="true" />
      ) : null}
      {markLegal ? <span className="legal-mark" aria-hidden="true" /> : null}
      {last ? <span className="last-mark" aria-hidden="true" /> : null}
    </>
  );
  if (canPlace) {
    return (
      <button
        type="button"
        className={className}
        data-square={square}
        aria-label={label}
        onClick={() => onPlace(square)}
      >
        {marks}
      </button>
    );
  }
  return (
    <div className={className} data-square={square} title={label}>
      {marks}
    </div>
  );
}

function squareLabel(
  square: string,
  cell: Cell,
  legal: boolean,
  last: boolean,
): string {
  const stone =
    cell === "black" ? "黒石" : cell === "white" ? "白石" : "空マス";
  const extras = [legal ? "合法手" : "", last ? "直前の着手" : ""].filter(
    (part) => part !== "",
  );
  if (extras.length === 0) {
    return `${square} ${stone}`;
  }
  return `${square} ${stone}（${extras.join("、")}）`;
}

export function Board({
  board,
  legalMoves,
  lastMove,
  showLegal,
  onPlace,
}: BoardProps) {
  const legal = new Set(legalMoves);
  const last = lastPlacedSquare(lastMove);
  return (
    <section className="board-grid" aria-label="リバーシ盤">
      <FileLabels prefix="top" />
      {RANKS_TOP_DOWN.map((rank) => (
        <RankRow
          key={rank}
          rank={rank}
          board={board}
          legal={legal}
          last={last}
          showLegal={showLegal}
          onPlace={onPlace}
        />
      ))}
      <FileLabels prefix="bottom" />
    </section>
  );
}

type RankRowProps = {
  rank: number;
  board: Cell[][];
  legal: ReadonlySet<string>;
  last: string | null;
  showLegal: boolean;
  onPlace?: (square: string) => void;
};

function RankRow({
  rank,
  board,
  legal,
  last,
  showLegal,
  onPlace,
}: RankRowProps) {
  return (
    <>
      <span className="board-rank">{rank}</span>
      {FILES.map((_, fileIndex) => {
        const square = algebraic(fileIndex, rank);
        return (
          <SquareView
            key={square}
            square={square}
            cell={board[rank - 1][fileIndex]}
            legal={legal.has(square)}
            last={last === square}
            showLegal={showLegal}
            onPlace={onPlace}
          />
        );
      })}
      <span className="board-rank">{rank}</span>
    </>
  );
}
