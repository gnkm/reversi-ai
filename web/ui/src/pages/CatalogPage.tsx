import { type FormEvent, useEffect, useState } from "react";
import { createGame, fetchCatalog } from "../api.ts";
import {
  displayNameOf,
  matchSummary,
  selectedSpecimenIds,
} from "../catalog.ts";
import { CatalogList } from "../components/CatalogList.tsx";
import {
  DEFAULT_AGENT_MOVE_INTERVAL_SECONDS,
  MAX_AGENT_MOVE_INTERVAL_SECONDS,
  MIN_AGENT_MOVE_INTERVAL_SECONDS,
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
  onStarted: (game: GameState, items: readonly CatalogItem[]) => void;
};

type AgentSlot = Color;

export function buildCreateGameRequest(input: {
  mode: GameMode;
  humanColor: Color;
  opponentId: string;
  blackId: string;
  whiteId: string;
  moveIntervalSeconds?: number;
}): CreateGameRequest {
  if (input.mode === "agent_vs_agent") {
    return {
      black: { kind: "specimen", specimen_id: input.blackId },
      white: { kind: "specimen", specimen_id: input.whiteId },
      move_interval_seconds:
        input.moveIntervalSeconds ?? DEFAULT_AGENT_MOVE_INTERVAL_SECONDS,
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
  const [activeSlot, setActiveSlot] = useState<AgentSlot>("black");
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
          moveIntervalSeconds: parseMoveIntervalSeconds(intervalSeconds),
        }),
      );
      onStarted(game, items);
    } catch {
      setStartError("対局を開始できませんでした。");
    } finally {
      setStarting(false);
    }
  }

  function handleSelectSpecimen(specimenId: string) {
    if (mode === "human_vs_agent") {
      setOpponentId(specimenId);
      return;
    }
    if (activeSlot === "black") {
      setBlackId(specimenId);
      return;
    }
    setWhiteId(specimenId);
  }

  const canStart = items.length > 0 && !starting;
  const summary = matchSummary({
    mode,
    humanColor,
    opponentId,
    blackId,
    whiteId,
    items,
  });
  const selectedIds = selectedSpecimenIds({
    mode,
    opponentId,
    blackId,
    whiteId,
  });

  return (
    <main className="page page-catalog">
      <h1>カタログ</h1>
      <p>
        表示名と説明を確認し、対局モード・石色・相手を選んで開始してください。
      </p>
      {loadError !== null ? <p className="error">{loadError}</p> : null}
      <form className="start-form" onSubmit={handleSubmit}>
        <ModeSegment mode={mode} onChange={setMode} />
        {mode === "human_vs_agent" ? (
          <ColorPicks value={humanColor} onChange={setHumanColor} />
        ) : (
          <AgentSlots
            items={items}
            blackId={blackId}
            whiteId={whiteId}
            activeSlot={activeSlot}
            intervalSeconds={intervalSeconds}
            onSlot={setActiveSlot}
            onInterval={setIntervalSeconds}
          />
        )}
        <CatalogList
          items={items}
          selectedIds={selectedIds}
          blackId={mode === "agent_vs_agent" ? blackId : undefined}
          whiteId={mode === "agent_vs_agent" ? whiteId : undefined}
          onSelect={handleSelectSpecimen}
        />
        {startError !== null ? <p className="error">{startError}</p> : null}
        <div className="catalog-dock">
          <p className="match-summary">{summary}</p>
          <button type="submit" className="btn-primary" disabled={!canStart}>
            対局を開始
          </button>
        </div>
      </form>
    </main>
  );
}

function ModeSegment({
  mode,
  onChange,
}: {
  mode: GameMode;
  onChange: (mode: GameMode) => void;
}) {
  return (
    <fieldset className="segmented">
      <legend>対局モード</legend>
      <div className="segmented-row">
        <label
          className={mode === "human_vs_agent" ? "segment is-on" : "segment"}
        >
          <input
            type="radio"
            name="mode"
            value="human_vs_agent"
            checked={mode === "human_vs_agent"}
            onChange={() => onChange("human_vs_agent")}
          />
          利用者対エージェント
        </label>
        <label
          className={mode === "agent_vs_agent" ? "segment is-on" : "segment"}
        >
          <input
            type="radio"
            name="mode"
            value="agent_vs_agent"
            checked={mode === "agent_vs_agent"}
            onChange={() => onChange("agent_vs_agent")}
          />
          エージェント対エージェント
        </label>
      </div>
    </fieldset>
  );
}

function ColorPicks({
  value,
  onChange,
}: {
  value: Color;
  onChange: (color: Color) => void;
}) {
  return (
    <fieldset className="color-picks">
      <legend>あなたの石色</legend>
      <div className="color-pick-row">
        <ColorPick
          color="black"
          label="黒（先手）"
          checked={value === "black"}
          onChange={onChange}
        />
        <ColorPick
          color="white"
          label="白（後手）"
          checked={value === "white"}
          onChange={onChange}
        />
      </div>
    </fieldset>
  );
}

function ColorPick({
  color,
  label,
  checked,
  onChange,
}: {
  color: Color;
  label: string;
  checked: boolean;
  onChange: (color: Color) => void;
}) {
  return (
    <label className={checked ? "color-pick is-on" : "color-pick"}>
      <input
        type="radio"
        name="color"
        value={color}
        checked={checked}
        onChange={() => onChange(color)}
      />
      <span className={`stone stone-${color}`} aria-hidden="true" />
      {label}
    </label>
  );
}

function AgentSlots({
  items,
  blackId,
  whiteId,
  activeSlot,
  intervalSeconds,
  onSlot,
  onInterval,
}: {
  items: readonly CatalogItem[];
  blackId: string;
  whiteId: string;
  activeSlot: AgentSlot;
  intervalSeconds: string;
  onSlot: (slot: AgentSlot) => void;
  onInterval: (value: string) => void;
}) {
  return (
    <div className="agent-setup">
      <div className="slot-row">
        <SlotButton
          slot="black"
          label="黒スロット"
          name={displayNameOf(items, blackId)}
          active={activeSlot === "black"}
          onClick={() => onSlot("black")}
        />
        <SlotButton
          slot="white"
          label="白スロット"
          name={displayNameOf(items, whiteId)}
          active={activeSlot === "white"}
          onClick={() => onSlot("white")}
        />
      </div>
      <label className="interval-label">
        着手間隔（秒）
        <input
          type="number"
          name="move-interval"
          min={MIN_AGENT_MOVE_INTERVAL_SECONDS}
          max={MAX_AGENT_MOVE_INTERVAL_SECONDS}
          step={0.1}
          value={intervalSeconds}
          onChange={(event) => onInterval(event.target.value)}
        />
      </label>
    </div>
  );
}

function SlotButton({
  slot,
  label,
  name,
  active,
  onClick,
}: {
  slot: Color;
  label: string;
  name: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={active ? "slot-card is-on" : "slot-card"}
      aria-pressed={active}
      onClick={onClick}
    >
      <span className={`stone stone-${slot}`} aria-hidden="true" />
      <span className="slot-copy">
        <span className="slot-label">{label}</span>
        <span className="slot-name">{name}</span>
      </span>
    </button>
  );
}
