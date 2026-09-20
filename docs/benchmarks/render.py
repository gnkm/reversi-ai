#!/usr/bin/env python3
"""round-robin.json と archive/ から GitHub 閲覧用の Markdown を書く。数値の正本は JSON。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

DIR = Path(__file__).resolve().parent
SOURCE = DIR / "round-robin.json"
OUTPUT = DIR / "round-robin.md"
ARCHIVE = DIR / "archive"
HISTORY = DIR / "history.md"

SHORT_NAME = {
    "random_uniform": "一様",
    "most_flips": "最多",
    "positional": "位置",
    "minimax": "ミニ",
    "opening": "定石",
    "ml": "ML",
    "lgbm": "LGBM",
    "rl": "RL",
    "nn": "NN",
    "jev": "Jev",
}


def fmt_points(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)


def mermaid_label(text: str) -> str:
    return '"' + text.replace('"', "") + '"'


def wdl(row: Mapping[str, object]) -> str:
    return f"{row['wins']}-{row['draws']}-{row['losses']}"


def cell_for(
    black: str,
    white: str,
    games: Sequence[Mapping[str, object]],
) -> str:
    if black == white:
        return "—"
    match = next(
        game
        for game in games
        if game["black"] == black and game["white"] == white
    )
    score = match["official_score"]
    assert isinstance(score, Mapping)
    mark = {"black": "勝", "white": "負", "draw": "分"}[str(match["winner"])]
    return f"{mark} {score['black']}-{score['white']}"


def series_rows(
    specimens: Sequence[Mapping[str, object]],
    names: Mapping[str, str],
    games: Sequence[Mapping[str, object]],
) -> list[list[str]]:
    ids = [str(item["specimen_id"]) for item in specimens]
    rows: list[list[str]] = []
    scoring = {"black": (1.0, 0.0), "white": (0.0, 1.0), "draw": (0.5, 0.5)}
    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            first = next(
                game
                for game in games
                if game["black"] == left and game["white"] == right
            )
            second = next(
                game
                for game in games
                if game["black"] == right and game["white"] == left
            )
            left_pts = 0.0
            right_pts = 0.0
            for game, a_is_black in ((first, True), (second, False)):
                winner = str(game["winner"])
                a_pts, b_pts = scoring[winner]
                if a_is_black:
                    left_pts += a_pts
                    right_pts += b_pts
                else:
                    left_pts += b_pts
                    right_pts += a_pts
            score_a = first["official_score"]
            score_b = second["official_score"]
            assert isinstance(score_a, Mapping)
            assert isinstance(score_b, Mapping)
            rows.append(
                [
                    names[left],
                    names[right],
                    f"{score_a['black']}-{score_a['white']}",
                    f"{score_b['black']}-{score_b['white']}",
                    f"{fmt_points(left_pts)}-{fmt_points(right_pts)}",
                ]
            )
    return rows


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def archive_filename(recorded_at: str) -> str:
    """`recorded_at`（例: 2026-09-20 13:23）から archive のファイル名を作る。"""
    stamp = str(recorded_at).strip().replace(":", "").replace(" ", "-")
    return f"{stamp}.json"


class Snapshot(NamedTuple):
    recorded_at: str
    models_commit: str
    trigger: str
    points: dict[str, float]
    specimen_ids: tuple[str, ...]
    href: str


def trigger_line(data: Mapping[str, object]) -> str:
    protocol = data["protocol"]
    assert isinstance(protocol, Mapping)
    notes = protocol["notes"]
    assert isinstance(notes, list)
    if not notes:
        return ""
    return str(notes[0])


def snapshot_from(data: Mapping[str, object], href: str) -> Snapshot:
    git = data["git"]
    assert isinstance(git, Mapping)
    specimens = data["specimens"]
    standings = data["standings"]
    assert isinstance(specimens, list)
    assert isinstance(standings, list)
    return Snapshot(
        recorded_at=str(data["recorded_at"]),
        models_commit=str(git["models_commit"]),
        trigger=trigger_line(data),
        points={
            str(row["specimen_id"]): float(row["points"]) for row in standings
        },
        specimen_ids=tuple(str(item["specimen_id"]) for item in specimens),
        href=href,
    )


def collect_snapshots(
    latest: Mapping[str, object],
    archive_dir: Path,
) -> list[Snapshot]:
    snapshots: list[Snapshot] = []
    seen: set[str] = set()
    if archive_dir.is_dir():
        for path in sorted(archive_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(data, dict)
            recorded_at = str(data["recorded_at"])
            if recorded_at in seen:
                continue
            seen.add(recorded_at)
            snapshots.append(snapshot_from(data, f"archive/{path.name}"))
    latest_at = str(latest["recorded_at"])
    if latest_at not in seen:
        snapshots.append(snapshot_from(latest, "round-robin.json"))
    snapshots.sort(key=lambda item: item.recorded_at, reverse=True)
    return snapshots


def specimen_columns(
    latest: Mapping[str, object],
    snapshots: Sequence[Snapshot],
) -> list[str]:
    specimens = latest["specimens"]
    assert isinstance(specimens, list)
    ids = [str(item["specimen_id"]) for item in specimens]
    seen = set(ids)
    for snap in snapshots:
        for sid in snap.specimen_ids:
            if sid not in seen:
                ids.append(sid)
                seen.add(sid)
    return ids


def render_history(
    latest: Mapping[str, object],
    archive_dir: Path,
) -> str:
    snapshots = collect_snapshots(latest, archive_dir)
    columns = specimen_columns(latest, snapshots)
    generation_rows = [
        [
            md_cell(snap.recorded_at),
            f"`{snap.models_commit}`",
            md_cell(snap.trigger),
            f"[JSON]({snap.href})",
        ]
        for snap in snapshots
    ]
    point_headers = ["記録"] + [md_cell(SHORT_NAME.get(sid, sid)) for sid in columns]
    point_rows = []
    for snap in snapshots:
        cells = [f"[{md_cell(snap.recorded_at)}]({snap.href})"]
        for sid in columns:
            if sid in snap.points:
                cells.append(fmt_points(snap.points[sid]))
            else:
                cells.append("—")
        point_rows.append(cells)

    lines = [
        "<!-- このファイルは docs/benchmarks/render.py が archive/ と round-robin.json から書く。手で直さない。 -->",
        "",
        "# 総当たりの勝ち点推移",
        "",
        "最新の数値の正本は [`round-robin.json`](round-robin.json) である。過去の正本は [`archive/`](archive/) に、現行と同じ形で残る。最新の閲覧用は [`round-robin.md`](round-robin.md) である。",
        "",
        "写しを作り直す:",
        "",
        "```bash",
        "python3 docs/benchmarks/render.py",
        "```",
        "",
        f"総当たりを取り直すときは、いまの `round-robin.json` を `archive/{archive_filename(str(latest['recorded_at']))}` のような名前でコピーしてから置き換え、上のコマンドで本ファイルと `round-robin.md` を書き直す。",
        "",
        "同じ `specimen_id` を世代をまたいで追う。旧世代を別個体としては出さない。",
        "",
        "## 世代",
        "",
        markdown_table(
            ["記録", "学習成果物", "きっかけ", "正本"],
            generation_rows,
        ),
        "",
        "## 勝ち点",
        "",
        "行が世代、列がカタログ個体の略称。勝ち点は勝 1・分 0.5。記録日時からその時点の JSON へ辿れる。",
        "",
        markdown_table(point_headers, point_rows),
        "",
    ]
    return "\n".join(lines)


def render(data: Mapping[str, object]) -> str:
    protocol = data["protocol"]
    git = data["git"]
    assert isinstance(protocol, Mapping)
    assert isinstance(git, Mapping)
    specimens = data["specimens"]
    standings = data["standings"]
    games = data["games"]
    assert isinstance(specimens, list)
    assert isinstance(standings, list)
    assert isinstance(games, list)
    names = {
        str(item["specimen_id"]): str(item["display_name"]) for item in specimens
    }
    ids = [str(item["specimen_id"]) for item in specimens]
    scoring = protocol["scoring"]
    assert isinstance(scoring, Mapping)
    notes = protocol["notes"]
    assert isinstance(notes, list)
    blobs = git["blobs"]
    assert isinstance(blobs, Mapping)

    ranked = sorted(standings, key=lambda row: int(row["rank"]))
    bar_labels = ", ".join(
        mermaid_label(SHORT_NAME.get(str(row["specimen_id"]), str(row["specimen_id"])))
        for row in ranked
    )
    bar_values = ", ".join(fmt_points(float(row["points"])) for row in ranked)
    max_points = max(float(row["points"]) for row in ranked)
    y_max = int(max_points) + (0 if max_points == int(max_points) else 1)
    if y_max % 2:
        y_max += 1
    games_as_black = int(ranked[0]["games"]) // 2 if ranked else 0

    overall_rows = [
        [
            str(row["rank"]),
            str(row["display_name"]),
            wdl(row),
            fmt_points(float(row["points"])),
            str(row["stones_for"]),
            str(row["stones_against"]),
            str(row["stone_diff"]),
        ]
        for row in ranked
    ]
    color_rows = []
    for row in ranked:
        black = row["as_black"]
        white = row["as_white"]
        assert isinstance(black, Mapping)
        assert isinstance(white, Mapping)
        color_rows.append(
            [
                str(row["display_name"]),
                wdl(black),
                fmt_points(float(black["points"])),
                wdl(white),
                fmt_points(float(white["points"])),
            ]
        )

    matrix_headers = ["黒 \\ 白"] + [SHORT_NAME.get(sid, sid) for sid in ids]
    matrix_rows = [
        [SHORT_NAME.get(black, black)]
        + [cell_for(black, white, games) for white in ids]
        for black in ids
    ]

    lines = [
        "<!-- このファイルは docs/benchmarks/render.py が round-robin.json から書く。手で直さない。 -->",
        "",
        "# カタログ個体の総当たり",
        "",
        "数値の正本は [`round-robin.json`](round-robin.json) である。本ファイルは GitHub 上の閲覧用の写しである。勝ち点の推移は [`history.md`](history.md) である。",
        "",
        "写しを作り直す:",
        "",
        "```bash",
        "python3 docs/benchmarks/render.py",
        "```",
        "",
        f"- 記録: {data['recorded_at']}",
        f"- 学習成果物のコミット: `{git['models_commit']}`",
        f"- 対局数: {protocol['games']}（先後入れ替えあり、自己対局なし）",
        f"- 入口: `{protocol['endpoint']}` / `{protocol['mode']}`",
        f"- 勝ち点: 勝 {fmt_points(float(scoring['win']))}、分 {fmt_points(float(scoring['draw']))}、負 {fmt_points(float(scoring['loss']))}",
        "",
        "対象ファイル:",
        "",
    ]
    for path in blobs:
        lines.append(f"- `{path}`")
    lines.append("")
    for note in notes:
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "## 勝ち点",
            "",
            "横軸はカタログ個体の略称、縦軸は勝ち点（勝 1・分 0.5）。",
            "",
            "```mermaid",
            "xychart-beta",
            '    title "総当たりの勝ち点"',
            f"    x-axis [{bar_labels}]",
            f'    y-axis "勝ち点" 0 --> {y_max}',
            f"    bar [{bar_values}]",
            "```",
            "",
            "## 順位",
            "",
            markdown_table(
                ["順", "個体", "勝-分-負", "点", "得石", "失石", "石差"],
                overall_rows,
            ),
            "",
            "## 先攻と後攻",
            "",
            f"各個体 {games_as_black} 局が先攻（黒）、{games_as_black} 局が後攻（白）。",
            "",
            markdown_table(
                ["個体", "先攻 勝-分-負", "先攻点", "後攻 勝-分-負", "後攻点"],
                color_rows,
            ),
            "",
            "## 対戦表（行が黒・列が白）",
            "",
            "セルは黒から見た勝敗と公式石数（黒-白）。対角は対局していない。",
            "",
            markdown_table(matrix_headers, matrix_rows),
            "",
            "## 2 局シリーズ",
            "",
            "同じ相手について、左の個体が黒の局と白の局。シリーズ点は左-右。",
            "",
            markdown_table(
                ["左", "右", "左が黒", "右が黒", "シリーズ点"],
                series_rows(specimens, names, games),
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    OUTPUT.write_text(render(data).rstrip() + "\n", encoding="utf-8")
    HISTORY.write_text(render_history(data, ARCHIVE).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
