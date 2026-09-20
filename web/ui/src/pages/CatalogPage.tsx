import { type FormEvent, useEffect, useState } from "react";
import { createGame, fetchCatalog } from "../api.ts";
import { CatalogList } from "../components/CatalogList.tsx";
import {
  DEFAULT_AGENT_MOVE_INTERVAL_SECONDS,
  MAX_AGENT_MOVE_INTERVAL_SECONDS,
  MIN_AGENT_MOVE_INTERVAL_SECONDS,
  moveIntervalMsFromSeconds,
  parseMoveIntervalSeconds,
} from "../moveInterval.ts";
import type {
  CatalogItem,
  Color,
  CreateGameRequest,
  GameMode,
  GameState,
} from "../types.ts";

type CatalogPageProps = {
  onStarted: (
    game: GameState,
    items: readonly CatalogItem[],
    moveIntervalMs: number,
  ) => void;
};

export function buildCreateGameRequest(input: {
  mode: GameMode;
  humanColor: Color;
  opponentId: string;
  blackId: string;
  whiteId: string;
}): CreateGameRequest {
  if (input.mode === "agent_vs_agent") {
    return {
      black: { kind: "specimen", specimen_id: input.blackId },
      white: { kind: "specimen", specimen_id: input.whiteId },
    };
  }
  const human = { kind: "human" as const };
  const opponent = {
    kind: "specimen" as const,
    specimen_id: input.opponentId,
  };
  if (input.humanColor === "black") {
    return { black: human, white: opponent };
  }
  return { black: opponent, white: human };
}

export function CatalogPage({ onStarted }: CatalogPageProps) {
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mode, setMode] = useState<GameMode>("human_vs_agent");
  const [humanColor, setHumanColor] = useState<Color>("black");
  const [opponentId, setOpponentId] = useState("");
  const [blackId, setBlackId] = useState("");
  const [whiteId, setWhiteId] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [intervalSeconds, setIntervalSeconds] = useState(
    String(DEFAULT_AGENT_MOVE_INTERVAL_SECONDS),
  );

  useEffect(() => {
    let cancelled = false;
    fetchCatalog()
      .then((next) => {
        if (cancelled) {
          return;
        }
        setItems(next);
        const first = next[0]?.specimen_id ?? "";
        setOpponentId(first);
        setBlackId(first);
        setWhiteId(first);
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError("カタログを取得できませんでした。");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStartError(null);
    setStarting(true);
    try {
      const game = await createGame(
        buildCreateGameRequest({
          mode,
          humanColor,
          opponentId,
          blackId,
          whiteId,
        }),
      );
      onStarted(
        game,
        items,
        moveIntervalMsFromSeconds(parseMoveIntervalSeconds(intervalSeconds)),
      );
    } catch {
      setStartError("対局を開始できませんでした。");
    } finally {
      setStarting(false);
    }
  }

  const canStart = items.length > 0 && !starting;

  return (
    <main className="page">
      <h1>カタログ</h1>
      <p>
        表示名と説明を確認し、対局モード・石色・相手を選んで開始してください。
      </p>
      {loadError !== null ? <p className="error">{loadError}</p> : null}
      <CatalogList items={items} />
      <form className="start-form" onSubmit={handleSubmit}>
        <fieldset>
          <legend>対局モード</legend>
          <label>
            <input
              type="radio"
              name="mode"
              value="human_vs_agent"
              checked={mode === "human_vs_agent"}
              onChange={() => setMode("human_vs_agent")}
            />
            利用者対エージェント
          </label>
          <label>
            <input
              type="radio"
              name="mode"
              value="agent_vs_agent"
              checked={mode === "agent_vs_agent"}
              onChange={() => setMode("agent_vs_agent")}
            />
            エージェント対エージェント
          </label>
        </fieldset>
        {mode === "human_vs_agent" ? (
          <>
            <fieldset>
              <legend>あなたの石色</legend>
              <label>
                <input
                  type="radio"
                  name="color"
                  value="black"
                  checked={humanColor === "black"}
                  onChange={() => setHumanColor("black")}
                />
                黒（先手）
              </label>
              <label>
                <input
                  type="radio"
                  name="color"
                  value="white"
                  checked={humanColor === "white"}
                  onChange={() => setHumanColor("white")}
                />
                白（後手）
              </label>
            </fieldset>
            <label className="select-label">
              対戦相手
              <select
                value={opponentId}
                onChange={(event) => setOpponentId(event.target.value)}
              >
                {items.map((item) => (
                  <option key={item.specimen_id} value={item.specimen_id}>
                    {item.display_name}
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : (
          <>
            <label className="select-label">
              黒を担当するエージェント
              <select
                value={blackId}
                onChange={(event) => setBlackId(event.target.value)}
              >
                {items.map((item) => (
                  <option
                    key={`black-${item.specimen_id}`}
                    value={item.specimen_id}
                  >
                    {item.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="select-label">
              白を担当するエージェント
              <select
                value={whiteId}
                onChange={(event) => setWhiteId(event.target.value)}
              >
                {items.map((item) => (
                  <option
                    key={`white-${item.specimen_id}`}
                    value={item.specimen_id}
                  >
                    {item.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="select-label">
              着手間隔（秒）
              <input
                type="number"
                name="move-interval"
                min={MIN_AGENT_MOVE_INTERVAL_SECONDS}
                max={MAX_AGENT_MOVE_INTERVAL_SECONDS}
                step={0.1}
                value={intervalSeconds}
                onChange={(event) => setIntervalSeconds(event.target.value)}
              />
            </label>
          </>
        )}
        {startError !== null ? <p className="error">{startError}</p> : null}
        <button type="submit" disabled={!canStart}>
          対局を開始
        </button>
      </form>
    </main>
  );
}
