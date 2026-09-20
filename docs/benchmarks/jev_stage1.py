#!/usr/bin/env python3
"""Jev 段階 1 の 4 構成を同じ相手・同じ条件で対局し、成績 JSON を書く。

資格情報と課金が要る対局は CI に載せない。ホストで明示的に走らせる。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STRATEGY_SRC = ROOT / "strategy" / "src"
if str(STRATEGY_SRC) not in sys.path:
    sys.path.insert(0, str(STRATEGY_SRC))

from reversi.agents import catalog, jev  # noqa: E402
from reversi.engine.board import Color  # noqa: E402
from reversi.engine.rules import (  # noqa: E402
    PassMove,
    Place,
    Position,
    initial_position,
    is_over,
    legal_places,
    play,
)
from reversi.engine.score import official_score, stone_counts  # noqa: E402

Chooser = Callable[[Position], Place | None]

DEFAULT_OPPONENTS = ("most_flips", "positional", "opening")
OUTPUT = Path(__file__).resolve().parent / "jev-stage1.json"


def _bind_secret_if_needed() -> Path | None:
    if jev.SECRET_PATH.is_file() and jev.SECRET_PATH.read_text(encoding="utf-8").strip():
        return None
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return None
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - 対局中は残す
        prefix="openrouter-api-key-",
        suffix=".txt",
        delete=False,
    )
    handle.write(key.encode("utf-8"))
    handle.close()
    path = Path(handle.name)
    jev.SECRET_PATH = path
    return path


def _play(black: Chooser, white: Chooser) -> dict[str, Any]:
    position = initial_position()
    while not is_over(position):
        if not legal_places(position):
            position = play(position, PassMove())
            continue
        chooser = black if position.side_to_move is Color.BLACK else white
        move = chooser(position)
        if not isinstance(move, Place):
            raise jev.ExternalModelError("着手不能")
        position = play(position, move)
    counts = stone_counts(position.board)
    score = official_score(position.board)
    return {
        "official_black": score.black,
        "official_white": score.white,
        "stones_black": counts.black,
        "stones_white": counts.white,
    }


def _jev_chooser() -> Chooser:
    def choose(position: Position) -> Place | None:
        return jev.choose_move(position)

    return choose


def _opponent_chooser(specimen_id: str) -> Chooser:
    def choose(position: Position) -> Place | None:
        return catalog.choose_move(specimen_id, position)

    return choose


def _result_from_jev_side(game: dict[str, Any], jev_is_black: bool) -> str:
    black = int(game["official_black"])
    white = int(game["official_white"])
    jev_score = black if jev_is_black else white
    opp_score = white if jev_is_black else black
    if jev_score > opp_score:
        return "win"
    if jev_score < opp_score:
        return "loss"
    return "draw"


def _game_key(game: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(game["config"]), str(game["opponent"]), str(game["jev_color"]))


def _ensure_output(path: Path) -> None:
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        probe = parent / f".{path.name}.write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise SystemExit(f"出力先を書けません: {path}") from exc


def _load_games(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(loaded, dict):
        return []
    games = loaded.get("games")
    if not isinstance(games, list):
        return []
    restored: list[dict[str, Any]] = []
    for item in games:
        if isinstance(item, dict) and {"config", "opponent", "jev_color"} <= set(item):
            restored.append(item)
    return restored


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - replace で原子的に置く
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    )
    tmp = Path(handle.name)
    try:
        handle.write(serialized.encode("utf-8"))
        handle.close()
        tmp.replace(path)
    except Exception:
        handle.close()
        tmp.unlink(missing_ok=True)
        raise


def _payload(
    rows: Sequence[Mapping[str, Any]],
    games: Sequence[Mapping[str, Any]],
    opponents: Sequence[str],
) -> dict[str, Any]:
    names = {row["name"] for row in rows}
    if names >= jev.STAGE1_CODE_ONLY:
        baseline = jev.select_stage1_baseline(rows)
    elif rows:
        baseline = str(rows[0]["name"])
    else:
        baseline = ""
    return {
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "baseline": baseline,
        "v1_constant_answer": jev._V1_CONSTANT_ANSWER,
        "protocol": {
            "opponents": list(opponents),
            "both_colors": True,
            "include_self_play": False,
            "scoring": {"win": 1.0, "draw": 0.5, "loss": 0.0},
            "notes": [
                "カタログに 4 体は置かず、検証用の切替で 4 構成を同じ相手・同じ条件で対局した。",
                "v1_constant は第 1 版の min-max 正規化と優先係数で、Jev の答えを 0.5 に固定した。",
                "v2_jev0 は現行の固定 scales 評価だけで、Jev 項は 0。",
                "v2_code0 は現行合成のコード項を 0 にし、Jev の Choice だけ。",
                "v2_as_is は prompts/jev.json の現行合成。",
                "基準線はコードだけの構成のうち勝ち点（同点なら石差・勝数）が最も高いもの。",
                "資格情報と課金が要る対局は CI に載せない。本スクリプトはホストで明示実行する。",
            ],
        },
        "configs": list(rows),
        "games": list(games),
    }


def _summarize(name: str, games: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(1 for game in games if game["result"] == "win")
    draws = sum(1 for game in games if game["result"] == "draw")
    losses = sum(1 for game in games if game["result"] == "loss")
    stone_diff = 0
    for game in games:
        jev_is_black = game["jev_color"] == "black"
        own = game["official_black"] if jev_is_black else game["official_white"]
        opp = game["official_white"] if jev_is_black else game["official_black"]
        stone_diff += int(own) - int(opp)
    return {
        "name": name,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "points": wins + 0.5 * draws,
        "stone_diff": stone_diff,
        "games": len(games),
    }


def _run_config(
    name: str,
    opponents: tuple[str, ...],
    both_colors: bool,
    existing: Sequence[Mapping[str, Any]],
    on_game: Callable[[dict[str, Any]], None],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    jev_side = _jev_chooser()
    games = [dict(game) for game in existing if game.get("config") == name]
    done = {_game_key(game) for game in games}
    colors = (True, False) if both_colors else (True,)
    with jev.stage1_config(name):
        for opponent_id in opponents:
            other = _opponent_chooser(opponent_id)
            for jev_is_black in colors:
                color = "black" if jev_is_black else "white"
                if (name, opponent_id, color) in done:
                    print(
                        f"{name} vs {opponent_id} "
                        f"({'黒' if jev_is_black else '白'}) skip",
                        flush=True,
                    )
                    continue
                black, white = (jev_side, other) if jev_is_black else (other, jev_side)
                raw = _play(black, white)
                record = {
                    "config": name,
                    "opponent": opponent_id,
                    "jev_color": color,
                    "result": _result_from_jev_side(raw, jev_is_black),
                    **raw,
                }
                games.append(record)
                on_game(record)
                print(
                    f"{name} vs {opponent_id} "
                    f"({'黒' if jev_is_black else '白'}) {record['result']} "
                    f"{raw['official_black']}-{raw['official_white']}",
                    flush=True,
                )
    return _summarize(name, games), games


def main() -> int:
    parser = argparse.ArgumentParser(description="Jev 段階 1 の 4 構成を同じ相手と対局する")
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT,
        help="書き出す JSON",
    )
    parser.add_argument(
        "--code-only",
        action="store_true",
        help="OpenRouter が要る構成を飛ばす（記録の正には使わない）",
    )
    parser.add_argument(
        "--opponents",
        nargs="+",
        default=list(DEFAULT_OPPONENTS),
        help="カタログ個体 ID",
    )
    args = parser.parse_args()
    output = args.output
    _ensure_output(output)
    jev._log_candidates = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    secret = _bind_secret_if_needed()
    configs = list(jev.STAGE1_CONFIG_NAMES)
    if args.code_only:
        configs = [name for name in configs if name in jev.STAGE1_CODE_ONLY]
    needs_model = any(name not in jev.STAGE1_CODE_ONLY for name in configs)
    if needs_model and not jev.SECRET_PATH.is_file():
        raise SystemExit("OpenRouter の資格情報が無く、jev: 0 以外の構成を対局できない")
    opponents = tuple(args.opponents)
    games = _load_games(output)

    def _save() -> None:
        rows = []
        for name in configs:
            played = [game for game in games if game.get("config") == name]
            if played:
                rows.append(_summarize(name, played))
        _atomic_write(output, _payload(rows, games, opponents))

    def _on_game(record: dict[str, Any]) -> None:
        games.append(record)
        _save()

    try:
        for name in configs:
            _run_config(
                name,
                opponents,
                both_colors=True,
                existing=games,
                on_game=_on_game,
            )
        _save()
    finally:
        if secret is not None:
            secret.unlink(missing_ok=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    print(f"wrote {output} baseline={payload.get('baseline', '')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
