#!/usr/bin/env python3
"""カタログ総当たりを、ホストの着手関数で直接進める。

対局 API が無いときの参考記録。CI では走らせない。
OpenRouter の鍵が環境変数にあるときは一時ファイルへ写し、Jev の読取先だけを差し替える。
鍵は標準出力にも正本 JSON にも書かない。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import Random
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STRATEGY_SRC = ROOT / "strategy" / "src"
if str(STRATEGY_SRC) not in sys.path:
    sys.path.insert(0, str(STRATEGY_SRC))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import round_robin

from reversi.agents.catalog import choose_move, items
from reversi.agents.jev import SECRET_PATH, ExternalModelError
from reversi.engine.rules import (
    PassMove,
    Place,
    initial_position,
    is_over,
    legal_places,
    play,
)
from reversi.engine.score import official_score

JST = timezone(timedelta(hours=9))
PROGRESS = Path("/tmp/rl-stage1-round-robin.jsonl")
_SECRET: Path | None = None


def bind_secret() -> Path | None:
    """鍵ファイルが無いときだけ、環境変数を一時ファイルへ写す。"""
    global _SECRET
    if SECRET_PATH.is_file() and SECRET_PATH.read_text(encoding="utf-8").strip():
        return None
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return None
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - 対局が終わるまで残す
        prefix="openrouter-api-key-",
        suffix=".txt",
        delete=False,
    )
    handle.write(key.encode("utf-8"))
    handle.close()
    path = Path(handle.name)
    path.chmod(0o600)
    _SECRET = path
    return path


def _init_worker(secret: str | None) -> None:
    if not secret:
        return
    from reversi.agents import jev

    jev.SECRET_PATH = Path(secret)


def play_pair(black: str, white: str, seed: int) -> dict[str, Any]:
    """初形から 1 局。勝者は公式スコア。"""
    rng = Random(f"{seed}:{black}:{white}")
    position = initial_position()
    ply = 0
    while not is_over(position):
        ply += 1
        if ply > 128:
            raise RuntimeError("手数の上限を超えた")
        places = legal_places(position)
        if not places:
            position = play(position, PassMove())
            continue
        side = black if position.side_to_move.value == "black" else white
        move = choose_move(side, position, rng)
        if not isinstance(move, Place) or move.square not in places:
            raise RuntimeError("合法手の外を選んだ")
        position = play(position, move)
    score = official_score(position.board)
    if score.black > score.white:
        winner = "black"
    elif score.white > score.black:
        winner = "white"
    else:
        winner = "draw"
    return {
        "black": black,
        "white": white,
        "winner": winner,
        "score_black": score.black,
        "score_white": score.white,
        "id": str(uuid.uuid4()),
        "is_over": True,
        "status": "completed",
    }


def play_with_retries(black: str, white: str, seed: int, retries: int) -> dict[str, Any]:
    last: Exception | None = None
    for _ in range(max(1, retries)):
        try:
            return play_pair(black, white, seed)
        except ExternalModelError as exc:
            last = exc
    raise RuntimeError(f"{black} vs {white} が継続不能") from last


def progress_identity(
    catalog: Sequence[dict[str, str]],
    blobs: dict[str, str],
    seed: int,
) -> dict[str, Any]:
    """通常版と同じ世代に、ホスト対局の乱数種を足す。"""
    identity = round_robin.progress_identity("in-process", catalog, blobs)
    identity["seed"] = int(seed)
    return identity


def prepare_local_progress(
    path: Path, identity: dict[str, Any]
) -> dict[tuple[str, str], dict[str, Any]]:
    """世代か seed が違う進捗は再利用しない。"""
    done = round_robin.prepare_progress(path, identity)
    meta = round_robin.read_progress_meta(path)
    if meta is None or meta.get("seed") != identity.get("seed"):
        raise SystemExit(
            "progress の seed が現行と違います。"
            f"削除するか --progress で別ファイルを指定してください: {path}"
        )
    return done


def self_check() -> None:
    identity = progress_identity(
        [{"specimen_id": "a"}, {"specimen_id": "b"}],
        {"models/rl.json": "abc"},
        20260922,
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "progress.jsonl"
        assert prepare_local_progress(path, identity) == {}
        round_robin.append_progress(
            path,
            {
                "black": "a",
                "white": "b",
                "winner": "black",
                "score_black": 40,
                "score_white": 24,
                "id": "g",
                "is_over": True,
                "status": "completed",
            },
        )
        resumed = prepare_local_progress(path, identity)
        assert resumed[("a", "b")]["winner"] == "black"
        other_seed = progress_identity(
            [{"specimen_id": "a"}, {"specimen_id": "b"}],
            {"models/rl.json": "abc"},
            1,
        )
        try:
            prepare_local_progress(path, other_seed)
        except SystemExit:
            pass
        else:
            raise AssertionError("seed が違う progress を再利用してはいけない")
        other_blobs = progress_identity(
            [{"specimen_id": "a"}, {"specimen_id": "b"}],
            {"models/rl.json": "other"},
            20260922,
        )
        try:
            prepare_local_progress(path, other_blobs)
        except SystemExit:
            pass
        else:
            raise AssertionError("学習成果物が違う progress を再利用してはいけない")
        stale = Path(tmp) / "stale.jsonl"
        stale.write_text(
            json.dumps({"black": "a", "white": "b", "winner": "black"}) + "\n",
            encoding="utf-8",
        )
        try:
            prepare_local_progress(stale, identity)
        except SystemExit:
            pass
        else:
            raise AssertionError("識別のない progress を再利用してはいけない")
    print("self-check ok", flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ホスト上でカタログ総当たりを記録する")
    parser.add_argument("--output", type=Path, default=round_robin.SOURCE)
    parser.add_argument("--archive-dir", type=Path, default=round_robin.ARCHIVE)
    parser.add_argument("--progress", type=Path, default=PROGRESS)
    parser.add_argument("--seed", type=int, default=20260922)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument("--self-check", action="store_true", help="対局せず進捗の世代検査だけを固定する")
    args = parser.parse_args(argv)
    if args.self_check:
        self_check()
        return 0
    secret = bind_secret()
    if secret is not None:
        from reversi.agents import jev

        jev.SECRET_PATH = secret
    catalog = [
        {
            "specimen_id": item.specimen_id,
            "display_name": item.display_name,
            "category": item.category,
        }
        for item in items()
    ]
    pairs = round_robin.make_pairs(catalog)
    blobs = round_robin.git_blobs(ROOT, round_robin.MODEL_PATHS)
    models_commit = round_robin.git_head(ROOT)
    round_robin.require_commit_blobs(
        models_commit,
        blobs,
        round_robin.git_tree_blobs(ROOT, models_commit, round_robin.MODEL_PATHS),
    )
    done = prepare_local_progress(
        args.progress, progress_identity(catalog, blobs, args.seed)
    )
    pending = [pair for pair in pairs if pair not in done]
    workers = args.workers if args.workers > 0 else (os.cpu_count() or 1)
    print(
        f"agents {[item['specimen_id'] for item in catalog]} "
        f"games {len(pairs)} pending {len(pending)} workers {workers}",
        flush=True,
    )
    results = [done[pair] for pair in pairs if pair in done]

    def _store(row: dict[str, Any]) -> None:
        round_robin.append_progress(args.progress, row)
        results.append(row)
        print(
            f"{len(results):03d}/{len(pairs)} {row['black']} vs {row['white']} "
            f"winner={row['winner']} {row['score_black']}-{row['score_white']}",
            flush=True,
        )

    if pending:
        if workers <= 1:
            for black, white in pending:
                _store(play_with_retries(black, white, args.seed, args.retries))
        else:
            with ProcessPoolExecutor(
                max_workers=workers,
                initializer=_init_worker,
                initargs=(str(secret) if secret is not None else None,),
            ) as pool:
                futures = {
                    pool.submit(play_with_retries, black, white, args.seed, args.retries): (
                        black,
                        white,
                    )
                    for black, white in pending
                }
                for future in as_completed(futures):
                    _store(future.result())
    if round_robin.git_blobs(ROOT, round_robin.MODEL_PATHS) != blobs:
        raise SystemExit("対局中に models/ が変わった。正本は書き換えない。")
    archived = round_robin.archive_current(args.output, args.archive_dir)
    if archived is not None:
        print(f"archived {archived}", flush=True)
    notes = [
        "強化学習 (自己対局＋読み) は線形 v を葉にした深さ 4 のアルファベータ。",
        "ホストの着手関数を直接呼んだ。対局 API は使っていない。",
        *args.note,
    ]
    payload = round_robin.build_payload(
        catalog,
        results,
        recorded_at=datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        models_commit=models_commit,
        blobs=blobs,
        extra_notes=notes,
        endpoint="in-process",
    )
    round_robin.atomic_write(args.output, payload)
    args.progress.unlink(missing_ok=True)
    print(f"wrote {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
