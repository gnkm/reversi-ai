# Jev 改善実験の知見（2026-09-20）

数値の正本は各段階の JSON と総当たりの JSON である。本ファイルはそれを要約し、段階をまたいだ判断と繰り返さないことを書く。表の小数は閲覧用に丸めた写しであり、再計算して正本にしない。`round-robin.md` / `history.md` のように [`render.py`](render.py) では生成しない。

提案書はシードであり、本ファイルは [`docs/source-of-truth/`](../source-of-truth/) には置かない。

## 経緯

生成 AI (Jev) は 2026-09-20 に 2 版を経て、提案書の 5 段階検証へ入った。

第 1 版（[#71](https://github.com/gnkm/reversi-ai/issues/71)）は、Jev に戦略上の優先を Noul / Score / Choice で答えさせ、コードが計算した着手後指標に係数として掛けた（優先合成）。カタログ個体としての総当たりは [2026-09-20 19:13](archive/2026-09-20-1913.json) で勝ち点 14.0、10 個体中 2 位である（[`history.md`](history.md)）。

第 2 版（[#80](https://github.com/gnkm/reversi-ai/issues/80)）は、コードが各合法手を 5 項目の事実で記述し、全合法手を Choice の選択肢にして Jev に選ばせ、コード評価と加算合成した。同じ総当たりの取り直しは [2026-09-20 20:46](round-robin.json) で勝ち点 7.0、6 位である。

成績低下を受け、提案書 [260920_jev-improvement-proposal.md](../source-of-truth/260920_jev-improvement-proposal.md) は「コードが絞り込み、Jev は候補の中から選ぶ」方針と段階 0–5 の検証を定めた。実装は [#82](https://github.com/gnkm/reversi-ai/issues/82)–[#87](https://github.com/gnkm/reversi-ai/issues/87)。段階 0 は候補手ログとバケット上限であり、成績の切り分けは段階 1 からである。

カタログ個体を第 1 版の優先合成へ戻す作業は [#107](https://github.com/gnkm/reversi-ai/issues/107) であり、本レポートとは独立である。本実験のあと、カタログ既定は段階 5 の判定によりコード最善（構成 `v2_jev0`）になっている。

## 段階ごとの結果

### 段階 1：成績低下の切り分け

記録: [`jev-stage1.json`](jev-stage1.json)（`recorded_at` 2026-09-20 13:07）。Issue [#83](https://github.com/gnkm/reversi-ai/issues/83)。

カタログに 4 体は置かず、検証用の切替で 4 構成を同じ相手（最多取り・位置評価・定石）・先後入れ替え・自己対局なしで対局した。各構成 6 局。基準線はコードだけの構成のうち、勝ち点（同点なら石差・勝数）が最も高いものである。記録では `baseline` が `v1_constant`。

| 構成 | 意味 | 勝 | 分 | 負 | 勝ち点 | 石差 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `v1_constant` | 第 1 版の正規化と優先係数。Jev の答えを 0.5 に固定 | 4 | 0 | 2 | 4.0 | 76 |
| `v2_jev0` | 第 2 版の固定 scales 評価だけ。Jev 項は 0 | 3 | 0 | 3 | 3.0 | −26 |
| `v2_code0` | 第 2 版合成のコード項を 0。Jev の Choice だけ | 4 | 0 | 2 | 4.0 | 16 |
| `v2_as_is` | `prompts/jev.json` の現行合成（第 2 版そのまま） | 2 | 0 | 4 | 2.0 | −90 |

判定: `v2_jev0` は `v1_constant` より勝ち点も石差も下である。同時に `v2_as_is` は 4 構成で最弱である。評価関数の変更と Jev の上書きの両方がありうる、という提案書 2.1 の切り分けは、この 4 行ではどちらも棄却できない。以降のオフライン評価は、コード最善（`margin = 0` / `code_best`）を基準線にした。

### 段階 2：局面単位のオフライン評価

記録: [`jev-stage2.json`](jev-stage2.json)（`recorded_at` 2026-09-20 13:46）。Issue [#84](https://github.com/gnkm/reversi-ai/issues/84)。

対局ログから合法手が 2 手以上の局面を序盤・中盤・終盤各 6、計 18 局面。正解は手元の αβ（深さ 4。空きマス 8 以下なら終局まで）。WTHOR は使っていない。絞り込みの初期値は `shortlist_size` 3、`margin` 0.5、`confidence_threshold` 0.3。損失 50 以上を大悪手とする。

| 方式 | n | 一致率 | 平均損失 | 大悪手率 |
| --- | ---: | ---: | ---: | ---: |
| `code_best`（コード評価の最善手） | 18 | 0.50 | 20.06 | 0.17 |
| `jev_all`（全合法手 Choice） | 18 | 0.39 | 31.89 | 0.33 |
| `shortlist`（絞り込み） | 18 | 0.50 | 23.83 | 0.22 |

`jev_all` と `shortlist` の平均損失はいずれも `code_best` より大きい。絞り込みは全合法手より損失は小さいが、コード最善を下回ってはいない。

`confidence_bins` は `jev_all` の答えを区間に分けた表である。提案書は「confidence が高いほど損失が小さければ、threshold による切替に根拠がある」と書いた。記録の区間表ではその関係は出ていない。

| 区間 | n | 一致率 | 平均損失 |
| --- | ---: | ---: | ---: |
| 0.0–0.2 | 1 | 0.00 | 2.0 |
| 0.2–0.4 | 4 | 0.25 | 43.75 |
| 0.4–0.6 | 1 | 1.00 | 0.0 |
| 0.6–0.8 | 2 | 1.00 | 0.0 |
| 0.8–1.0 | 10 | 0.30 | 39.7 |

最も高い区間（0.8–1.0）の平均損失 39.7 は、最も低い区間（0.0–0.2）の 2.0 より大きい。標本は区間によって 1 件から 10 件まで偏る。

### 段階 3：プロンプトを 1 変更ずつ

記録: [`jev-stage3.json`](jev-stage3.json)（`recorded_at` 2026-09-20 14:38）。Issue [#85](https://github.com/gnkm/reversi-ai/issues/85)。

指標は絞り込み方式の平均損失。改訂用 18 局面で下がった変更だけを別 18 局面（holdout）でも測り、そちらでも下がったものだけ採用する。`accepted_changes` は空配列である。予定した 6 件はいずれも `accepted` が false。

| 変更 | 改訂用 平均損失 前→後 | holdout 前→後 | 採用 |
| --- | --- | --- | --- |
| `instructions_reference_stage_and_side` | 40.22 → 40.22 | （改訂用で下がらず未測定） | 不採用 |
| `drop_objective` | 40.22 → 39.44 | 14.06 → 14.22 | 不採用 |
| `gives_corner_newly` | 40.22 → 34.22 | 14.06 → 14.06 | 不採用 |
| `add_takes_edge` | 40.22 → 40.22 | （改訂用で下がらず未測定） | 不採用 |
| `add_stable_increase` | 40.22 → 40.22 | （改訂用で下がらず未測定） | 不採用 |
| `add_reply_change` | 40.22 → 40.22 | （改訂用で下がらず未測定） | 不採用 |

`drop_objective` は改訂用ではわずかに下がったが holdout では上がった。`gives_corner_newly` は改訂用で大きく下がって見えるが holdout は同値である。holdout 全体の `improved` は false。予定したプロンプト変更は holdout で採用されなかった。

### 段階 4：絞り込みパラメータの格子

記録: [`jev-stage4.json`](jev-stage4.json)（`recorded_at` 2026-09-20 14:56）。Issue [#86](https://github.com/gnkm/reversi-ai/issues/86)。

局面集合は段階 2 の 18 局面。`margin = 0` がコード最善と同じ手を選ぶ基準線で、平均損失は 20.06（`baseline_mean_loss` / `margin_zero_mean_loss`）。格子は `shortlist_size` ∈ {2,3,4,5}、`margin` ∈ {0, 0.25, 0.5, 1.0, 2.0}、`confidence_threshold` ∈ {0, 0.3, 0.5, 0.8, 1.0}。プロンプト文言は変えていない。

`beats_baseline` は true。指名した 1 組は次である。

| 項目 | 値 |
| --- | --- |
| `shortlist_size` | 4 |
| `margin` | 2.0 |
| `confidence_threshold` | 0.5 |
| 平均損失 | 19.44 |

基準線との差は約 0.61 である。記録の注記どおり、オフラインの差は探索損失であり、対局の勝率の有意差ではない。`return_to_stage3` は false のため、この指名設定だけを段階 5 の対局へ送った。

### 段階 5：対局による最終確認

記録: [`jev-stage5.json`](jev-stage5.json)（`recorded_at` 2026-09-20 21:00）。Issue [#87](https://github.com/gnkm/reversi-ai/issues/87)。

開始局面 24（初形から 4/6/8 手を乱択。`seed` 20260920）。各局面で先後入れ替え、計 48 局。基準線はコード最善（`margin = 0`）。候補は段階 4 の指名設定。採用条件は、平均石差が正、勝率が基準線を下回らず、対の石差の片側符号検定が有意（α = 0.05）であること。

| 指標 | 値 |
| --- | --- |
| 候補の勝 / 分 / 負 | 9 / 1 / 38 |
| 候補の勝率 | 0.198 |
| 基準線の勝率 | 0.802 |
| 平均石差（候補−基準線） | −13.98 |
| 符号検定 | n=24、正 4、負 20、同点 0、p≈0.9999 |
| `accepted` | **false**（不採用） |
| `catalog_policy` | `code_only_v2_jev0` |
| `return_to_stage3_and_4` | true |

オフライン 18 局面で見えた微小な平均損失差（19.44 対 20.06）は対局に一般化しなかった。段階 5 は不採用であり、カタログ既定をコード最善（`v2_jev0`）にした。

この既定は、カテゴリが生成 AI である個体は OpenRouter への呼出しによって合法手を選ばなければならない [SRS-FUN-021](../srs.md#srs-fun-021-生成-ai-カテゴリ) と、カタログの「生成 AI (Jev)」が `typesafe/jev-1.13` を呼び出さなければならない [SRS-FUN-022](../srs.md#srs-fun-022-生成-ai-jev) と衝突する。shall の変更は本レポートの範囲外である。戻す作業は [#107](https://github.com/gnkm/reversi-ai/issues/107)。

## 横断の知見

根拠は上の各 JSON である。

1. **第 2 版の成績低下は、評価関数の変更と Jev の上書きの両方がありうる。** 段階 1 で `v2_jev0` は `v1_constant` より弱く、`v2_as_is` はさらに弱い。一方だけを主因とは言えない。
2. **コード最善より Jev 単独・絞り込みの平均損失が大きい。** 段階 2 の `code_best` 20.06 に対し `jev_all` 31.89、`shortlist` 23.83。
3. **confidence が高いほど損失が小さい、という関係は段階 2 の区間表では出ていない。** 最高区間の平均損失が最低区間より大きい。
4. **予定したプロンプト変更は holdout で採用されなかった。** 段階 3 の `accepted_changes` は空である。
5. **オフライン 18 局面の微小な平均損失差は対局に一般化しなかった。** 段階 4 の指名設定（平均損失 19.44）は段階 5 で勝率 0.198、平均石差 −13.98、`accepted` は false。
6. **段階 5 は不採用であり、カタログ既定をコード最善にした。** それは SRS-FUN-021 / SRS-FUN-022 と衝突する。

## 繰り返さないこと

同じプロトコル（18 局面・同じ 5 項目説明・格子再実行）を段階 3・4 へ戻しても、またノイズで「勝ち」が出るリスクがある。

段階 3 では改訂用だけで下がって見える変更（`drop_objective`、`gives_corner_newly`）が holdout では採用条件を満たさなかった。段階 4 では同一 18 局面の格子で基準線を約 0.61 下回る点が 1 つ指名されたが、段階 5 の 48 局では候補が大差で負けた。局面集合が小さく、説明項目が第 2 版のままなら、格子の「勝ち」は探索損失の標本誤差でありうる。段階 5 の `return_to_stage3_and_4` が true でも、説明も局面集合も変えずに同じ格子を回すことは、採用基準を満たしたように見える設定を再び拾うだけになりやすい。

## 出典

- 提案書: [`docs/source-of-truth/260920_jev-improvement-proposal.md`](../source-of-truth/260920_jev-improvement-proposal.md)（シード。AI は編集しない）
- 段階記録: [`jev-stage1.json`](jev-stage1.json)、[`jev-stage2.json`](jev-stage2.json)、[`jev-stage3.json`](jev-stage3.json)、[`jev-stage4.json`](jev-stage4.json)、[`jev-stage5.json`](jev-stage5.json)
- 総当たり: 最新 [`round-robin.json`](round-robin.json)（2026-09-20 20:46、第 2 版）、第 1 版 [`archive/2026-09-20-1913.json`](archive/2026-09-20-1913.json)。閲覧用 [`round-robin.md`](round-robin.md)、推移 [`history.md`](history.md)
- 関連 Issue: 実験 [#82](https://github.com/gnkm/reversi-ai/issues/82)–[#87](https://github.com/gnkm/reversi-ai/issues/87)（完了）。実験前の 2 版 [#71](https://github.com/gnkm/reversi-ai/issues/71)、[#80](https://github.com/gnkm/reversi-ai/issues/80)。優先合成へ戻す [#107](https://github.com/gnkm/reversi-ai/issues/107)（本レポートとは独立）
