#!/usr/bin/env python3
"""カタログ個体の総当たりを、起動済みの対局 API へ HTTPS で順次問い合わせる。

対局の再実行は CI に載せない。ホストで明示的に走らせる。
起動は README の対局コマンドのまま。本スクリプトはコンテナを起動しない。
OpenRouter の鍵は戦略コンテナだけが読む。ホストの Python は鍵を受け取らない。
"""

from __future__ import annotations

import argparse
import json
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = HERE / "round-robin.json"
ARCHIVE = HERE / "archive"
PROGRESS = HERE / ".round-robin-progress.jsonl"
ORIGIN = "https://127.0.0.1:3000"
MODEL_PATHS = (
    "models/ml.json",
    "models/lgbm.txt",
    "models/rl.json",
    "models/nn.onnx",
)
JST = timezone(timedelta(hours=9))
CTX = ssl._create_unverified_context()
SEARCH = frozenset({"minimax", "alphabeta"})
GENERATIVE = "generative_ai"
PROGRESS_META = "progress_meta"


def protocol_notes(count: int, extra: Sequence[str]) -> list[str]:
    return [
        f"カタログ {count} 個体の総当たり。各対について先攻（黒）と後攻（白）を入れ替えた 2 局。",
        "ランダム (一様) と生成 AI (Jev) は非決定的なので、同じ重みでも再実行で勝敗は変わりうる。",
        "新しい対局開始は進行中の 1 局を置き換えるため、局は順次実行した。",
        "この記録は git.blobs の学習成果物に対するスナップショットである。現行の models/ と blob が異なれば成績は一致しない。",
        *extra,
    ]


def archive_filename(recorded_at: str) -> str:
    stamp = str(recorded_at).strip().replace(":", "").replace(" ", "-")
    return f"{stamp}.json"


def make_pairs(items: Sequence[Mapping[str, str]]) -> list[tuple[str, str]]:
    ids = [str(item["specimen_id"]) for item in items]
    return [(black, white) for black in ids for white in ids if black != white]


def failed(row: Mapping[str, Any]) -> bool:
    return (
        (not row.get("is_over"))
        or bool(row.get("timeout"))
        or bool(row.get("unplayable_reason"))
        or row.get("winner") is None
    )


def load_done(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    done: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("kind") == PROGRESS_META or failed(row):
            continue
        done[(str(row["black"]), str(row["white"]))] = row
    return done


def progress_identity(
    origin: str,
    items: Sequence[Mapping[str, str]],
    blobs: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "kind": PROGRESS_META,
        "endpoint": origin,
        "specimen_ids": [str(item["specimen_id"]) for item in items],
        "blobs": dict(blobs),
    }


def identity_matches(stored: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return (
        stored.get("endpoint") == expected["endpoint"]
        and stored.get("specimen_ids") == expected["specimen_ids"]
        and stored.get("blobs") == expected["blobs"]
    )


def read_progress_meta(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("kind") == PROGRESS_META:
            return row
        return None
    return None


def prepare_progress(
    path: Path, identity: Mapping[str, Any]
) -> dict[tuple[str, str], dict[str, Any]]:
    if path.exists() and path.stat().st_size > 0:
        meta = read_progress_meta(path)
        if meta is None:
            raise SystemExit(
                f"progress に世代識別がありません。削除するか --progress で別ファイルを指定してください: {path}"
            )
        if not identity_matches(meta, identity):
            raise SystemExit(
                f"progress の世代が現行の入口・カタログ・学習成果物と違います。"
                f"削除するか --progress で別ファイルを指定してください: {path}"
            )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        append_progress(path, identity)
    return load_done(path)


def wait_limit(black: str, white: str, categories: Mapping[str, str]) -> tuple[int, float]:
    cats = {categories[black], categories[white]}
    if GENERATIVE in cats:
        return 1800, 0.5
    if black in SEARCH or white in SEARCH:
        return 600, 0.2
    return 180, 0.05


def request(
    origin: str,
    method: str,
    path: str,
    body: Mapping[str, Any] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Origin"] = origin
    req = urllib.request.Request(
        origin + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=timeout) as res:
            payload = json.loads(res.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise urllib.error.URLError(
            f"{method} {path} HTTP {exc.code}: {detail}"
        ) from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"API の応答がオブジェクトではない: {path}")
    return payload


def wait_finished(
    origin: str,
    game_id: str,
    limit: int,
    interval: float,
    started: float,
) -> dict[str, Any]:
    while True:
        game = request(origin, "GET", f"/api/games/{game_id}")
        if game.get("is_over") or game.get("status") != "in_progress":
            return game
        if time.monotonic() - started > limit:
            game["_timeout"] = True
            return game
        time.sleep(interval)


def play_game(
    origin: str,
    black: str,
    white: str,
    names: Mapping[str, str],
    categories: Mapping[str, str],
) -> dict[str, Any]:
    limit, interval = wait_limit(black, white, categories)
    started = time.monotonic()
    created = request(
        origin,
        "POST",
        "/api/games",
        {
            "black": {"kind": "specimen", "specimen_id": black},
            "white": {"kind": "specimen", "specimen_id": white},
        },
        timeout=30,
    )
    game_id = str(created["id"])
    finished = wait_finished(origin, game_id, limit, interval, started)
    result = finished.get("result") or {}
    score = finished.get("official_score") or {}
    return {
        "black": black,
        "white": white,
        "black_name": names[black],
        "white_name": names[white],
        "status": finished.get("status"),
        "is_over": finished.get("is_over"),
        "winner": result.get("winner") if isinstance(result, Mapping) else None,
        "score_black": score.get("black") if isinstance(score, Mapping) else None,
        "score_white": score.get("white") if isinstance(score, Mapping) else None,
        "unplayable_reason": finished.get("unplayable_reason"),
        "elapsed_s": round(time.monotonic() - started, 3),
        "timeout": bool(finished.get("_timeout")),
        "id": game_id,
    }


def blank_stat() -> dict[str, Any]:
    return {
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "points": 0.0,
        "stones_for": 0,
        "stones_against": 0,
        "stone_diff": 0,
    }


def add_stat(
    stat: dict[str, Any],
    scored: int,
    against: int,
    outcome: str,
) -> None:
    stat["stones_for"] += scored
    stat["stones_against"] += against
    stat["stone_diff"] += scored - against
    if outcome == "win":
        stat["wins"] += 1
        stat["points"] += 1.0
    elif outcome == "draw":
        stat["draws"] += 1
        stat["points"] += 0.5
    else:
        stat["losses"] += 1


def color_view(stat: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "wins": stat["wins"],
        "draws": stat["draws"],
        "losses": stat["losses"],
        "points": stat["points"],
        "stones_for": stat["stones_for"],
        "stones_against": stat["stones_against"],
        "stone_diff": stat["stone_diff"],
    }


def build_payload(
    items: Sequence[Mapping[str, str]],
    rows: Sequence[Mapping[str, Any]],
    *,
    recorded_at: str,
    models_commit: str,
    blobs: Mapping[str, str],
    extra_notes: Sequence[str],
    endpoint: str,
) -> dict[str, Any]:
    ids = [str(item["specimen_id"]) for item in items]
    names = {str(item["specimen_id"]): str(item["display_name"]) for item in items}
    categories = {str(item["specimen_id"]): str(item["category"]) for item in items}
    by_pair = {(str(row["black"]), str(row["white"])): row for row in rows}
    expected = make_pairs(items)
    if set(by_pair) != set(expected):
        raise SystemExit("終局した対がカタログの総当たりと一致しない")
    overall = {sid: blank_stat() for sid in ids}
    as_black = {sid: blank_stat() for sid in ids}
    as_white = {sid: blank_stat() for sid in ids}
    games: list[dict[str, Any]] = []
    for black, white in expected:
        row = by_pair[(black, white)]
        scored_black = int(row["score_black"])
        scored_white = int(row["score_white"])
        winner = str(row["winner"])
        if winner == "black":
            add_stat(overall[black], scored_black, scored_white, "win")
            add_stat(as_black[black], scored_black, scored_white, "win")
            add_stat(overall[white], scored_white, scored_black, "loss")
            add_stat(as_white[white], scored_white, scored_black, "loss")
        elif winner == "white":
            add_stat(overall[black], scored_black, scored_white, "loss")
            add_stat(as_black[black], scored_black, scored_white, "loss")
            add_stat(overall[white], scored_white, scored_black, "win")
            add_stat(as_white[white], scored_white, scored_black, "win")
        elif winner == "draw":
            add_stat(overall[black], scored_black, scored_white, "draw")
            add_stat(as_black[black], scored_black, scored_white, "draw")
            add_stat(overall[white], scored_white, scored_black, "draw")
            add_stat(as_white[white], scored_white, scored_black, "draw")
        else:
            raise SystemExit(f"未知の勝者です: {winner}")
        games.append(
            {
                "black": black,
                "white": white,
                "winner": winner,
                "official_score": {"black": scored_black, "white": scored_white},
                "status": "completed",
                "game_id": row["id"],
            }
        )
    opponents = len(ids) - 1
    per_side = opponents
    ranked = sorted(
        ids,
        key=lambda sid: (-overall[sid]["points"], -overall[sid]["stone_diff"], sid),
    )
    standings = []
    for rank, sid in enumerate(ranked, 1):
        total = overall[sid]
        games_played = total["wins"] + total["draws"] + total["losses"]
        if games_played != per_side * 2:
            raise SystemExit(f"{sid} の局数が {games_played}")
        standings.append(
            {
                "rank": rank,
                "specimen_id": sid,
                "display_name": names[sid],
                "games": games_played,
                "wins": total["wins"],
                "draws": total["draws"],
                "losses": total["losses"],
                "points": total["points"],
                "stones_for": total["stones_for"],
                "stones_against": total["stones_against"],
                "stone_diff": total["stone_diff"],
                "as_black": color_view(as_black[sid]),
                "as_white": color_view(as_white[sid]),
            }
        )
    return {
        "recorded_at": recorded_at,
        "git": {"models_commit": models_commit, "blobs": dict(blobs)},
        "protocol": {
            "endpoint": endpoint,
            "mode": "agent_vs_agent",
            "both_colors": True,
            "include_self_play": False,
            "games": len(games),
            "scoring": {"win": 1.0, "draw": 0.5, "loss": 0.0},
            "notes": protocol_notes(len(ids), extra_notes),
        },
        "specimens": [
            {
                "specimen_id": sid,
                "display_name": names[sid],
                "category": categories[sid],
            }
            for sid in ids
        ],
        "standings": standings,
        "games": games,
    }


def git_blobs(root: Path, paths: Sequence[str]) -> dict[str, str]:
    blobs: dict[str, str] = {}
    for rel in paths:
        digest = subprocess.check_output(
            ["git", "hash-object", rel], cwd=root, text=True
        ).strip()
        blobs[rel] = digest
    return blobs


def git_head(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
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


def append_progress(path: Path, row: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")


def catalog_items(origin: str) -> list[dict[str, str]]:
    payload = request(origin, "GET", "/api/catalog")
    raw = payload.get("items")
    if not isinstance(raw, list) or not raw:
        raise SystemExit("カタログが空です")
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise SystemExit("カタログ項目の形が不正です")
        specimen_id = str(item["specimen_id"])
        if specimen_id in seen:
            raise SystemExit(f"個体 ID が重複しています: {specimen_id}")
        seen.add(specimen_id)
        items.append(
            {
                "specimen_id": specimen_id,
                "display_name": str(item["display_name"]),
                "category": str(item["category"]),
            }
        )
    return items


def play_with_retries(
    origin: str,
    black: str,
    white: str,
    names: Mapping[str, str],
    categories: Mapping[str, str],
    retries: int,
) -> dict[str, Any]:
    last: dict[str, Any] | None = None
    for attempt in range(1, retries + 1):
        try:
            row = play_game(origin, black, white, names, categories)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            row = {
                "black": black,
                "white": white,
                "black_name": names[black],
                "white_name": names[white],
                "status": "error",
                "is_over": False,
                "winner": None,
                "score_black": None,
                "score_white": None,
                "unplayable_reason": str(exc),
                "elapsed_s": 0.0,
                "timeout": False,
                "id": None,
            }
        last = row
        if not failed(row):
            return row
        print(
            f"retry {attempt}/{retries} {names[black]} vs {names[white]} "
            f"status={row.get('status')} reason={row.get('unplayable_reason')}",
            flush=True,
        )
        time.sleep(3 * attempt)
    assert last is not None
    return last


def archive_current(source: Path, archive_dir: Path) -> Path | None:
    if not source.exists():
        return None
    current = json.loads(source.read_text(encoding="utf-8"))
    recorded = str(current["recorded_at"])
    dest = archive_dir / archive_filename(recorded)
    if dest.exists():
        existing = dest.read_text(encoding="utf-8")
        if existing != source.read_text(encoding="utf-8"):
            raise SystemExit(f"archive 先が既にあり中身が違います: {dest}")
        return dest
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def self_check() -> None:
    items = (
        {
            "specimen_id": "alpha",
            "display_name": "A",
            "category": "rule_based",
        },
        {
            "specimen_id": "beta",
            "display_name": "B",
            "category": "random",
        },
    )
    assert make_pairs(items) == [("alpha", "beta"), ("beta", "alpha")]
    assert failed(
        {
            "is_over": True,
            "winner": None,
            "unplayable_reason": "external_model_failed",
            "timeout": False,
        }
    )
    assert not failed(
        {
            "is_over": True,
            "winner": "black",
            "unplayable_reason": None,
            "timeout": False,
        }
    )
    rows = (
        {
            "black": "alpha",
            "white": "beta",
            "winner": "black",
            "score_black": 40,
            "score_white": 24,
            "id": "g-black",
            "is_over": True,
            "unplayable_reason": None,
            "timeout": False,
        },
        {
            "black": "beta",
            "white": "alpha",
            "winner": "draw",
            "score_black": 32,
            "score_white": 32,
            "id": "g-white",
            "is_over": True,
            "unplayable_reason": None,
            "timeout": False,
        },
    )
    payload = build_payload(
        items,
        rows,
        recorded_at="2026-09-21 16:00",
        models_commit="abc",
        blobs={"models/ml.json": "def"},
        extra_notes=("世代の注記。",),
        endpoint=ORIGIN,
    )
    assert payload["protocol"]["games"] == 2
    assert payload["protocol"]["both_colors"] is True
    assert payload["protocol"]["include_self_play"] is False
    assert payload["standings"][0]["specimen_id"] == "alpha"
    assert payload["standings"][0]["points"] == 1.5
    assert payload["standings"][1]["points"] == 0.5
    assert archive_filename("2026-09-21 15:55") == "2026-09-21-1555.json"
    identity = progress_identity(ORIGIN, items, {"models/ml.json": "def"})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "progress.jsonl"
        done = prepare_progress(path, identity)
        assert done == {}
        append_progress(
            path,
            {
                "black": "alpha",
                "white": "beta",
                "winner": "black",
                "score_black": 40,
                "score_white": 24,
                "id": "g-black",
                "is_over": True,
                "unplayable_reason": None,
                "timeout": False,
            },
        )
        resumed = prepare_progress(path, identity)
        assert resumed[("alpha", "beta")]["winner"] == "black"
        other = progress_identity(ORIGIN, items, {"models/ml.json": "other"})
        try:
            prepare_progress(path, other)
        except SystemExit:
            pass
        else:
            raise AssertionError("世代が違う progress を再利用してはいけない")
        stale = Path(tmp) / "stale.jsonl"
        stale.write_text(
            json.dumps({"black": "alpha", "white": "beta", "winner": "black"}) + "\n",
            encoding="utf-8",
        )
        try:
            prepare_progress(stale, identity)
        except SystemExit:
            pass
        else:
            raise AssertionError("識別のない progress を再利用してはいけない")
    print("self-check ok", flush=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="起動済みの対局 API でカタログ総当たりを記録する"
    )
    parser.add_argument("--endpoint", default=ORIGIN, help="対局 API の入口")
    parser.add_argument("--output", type=Path, default=SOURCE, help="正本 JSON")
    parser.add_argument("--archive-dir", type=Path, default=ARCHIVE, help="前回正本の置き場")
    parser.add_argument("--progress", type=Path, default=PROGRESS, help="再開用 jsonl")
    parser.add_argument("--retries", type=int, default=5, help="1 局あたりの再試行回数")
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        help="protocol.notes に足す世代注記。繰り返し可",
    )
    parser.add_argument("--dry-run", action="store_true", help="組だけ出して対局しない")
    parser.add_argument("--self-check", action="store_true", help="API を呼ばず集計を固定する")
    parser.add_argument("--no-archive", action="store_true", help="現行正本を archive しない")
    return parser.parse_args(argv)


def run_tournament(args: argparse.Namespace) -> int:
    origin = str(args.endpoint).rstrip("/")
    items = catalog_items(origin)
    names = {item["specimen_id"]: item["display_name"] for item in items}
    categories = {item["specimen_id"]: item["category"] for item in items}
    pairs = make_pairs(items)
    print(f"agents {[item['specimen_id'] for item in items]}", flush=True)
    print(f"games {len(pairs)}", flush=True)
    if args.dry_run:
        for black, white in pairs:
            print(f"{names[black]} vs {names[white]}", flush=True)
        return 0
    blobs = git_blobs(ROOT, MODEL_PATHS)
    done = prepare_progress(
        args.progress, progress_identity(origin, items, blobs)
    )
    results: list[dict[str, Any]] = []
    for index, (black, white) in enumerate(pairs, 1):
        existing = done.get((black, white))
        if existing is not None:
            row = existing
            print(
                f"{index:03d}/{len(pairs)} skip {names[black]} vs {names[white]} "
                f"winner={row['winner']} {row['score_black']}-{row['score_white']}",
                flush=True,
            )
        else:
            row = play_with_retries(
                origin,
                black,
                white,
                names,
                categories,
                max(1, args.retries),
            )
            append_progress(args.progress, row)
            extra = ""
            if row.get("unplayable_reason"):
                extra = f" reason={row['unplayable_reason']}"
            print(
                f"{index:03d}/{len(pairs)} {names[black]} vs {names[white]} -> "
                f"{row.get('status')} winner={row.get('winner')} "
                f"{row.get('score_black')}-{row.get('score_white')} "
                f"{row.get('elapsed_s')}s{extra}",
                flush=True,
            )
        results.append(row)
    unfinished = [row for row in results if failed(row)]
    if unfinished:
        print(f"未終局 {len(unfinished)} 局。正本は書き換えない。", flush=True)
        return 1
    if not args.no_archive:
        archived = archive_current(args.output, args.archive_dir)
        if archived is not None:
            print(f"archived {archived}", flush=True)
    payload = build_payload(
        items,
        results,
        recorded_at=datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        models_commit=git_head(ROOT),
        blobs=blobs,
        extra_notes=tuple(args.note),
        endpoint=origin,
    )
    atomic_write(args.output, payload)
    args.progress.unlink(missing_ok=True)
    print(f"wrote {args.output}", flush=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_check:
        self_check()
        return 0
    return run_tournament(args)


if __name__ == "__main__":
    sys.exit(main())
