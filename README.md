# Reversi AI

![CI](https://github.com/gnkm/reversi-ai/actions/workflows/ci.yml/badge.svg)

自分のパソコンのブラウザから、エージェントとリバーシ（オセロ）を対戦できるサービスです。エージェント同士の対戦を見ることもできます。

画面の言葉は日本語です。ブラウザは **Google Chrome** を使ってください。このサービスはインターネットへ公開せず、起動したパソコンの中だけで使います。アカウント登録はありません。

## できること

- カタログのカード（名前と説明）から、対戦相手のエージェントを個体ごとに選ぶ
- 自分がエージェントと対戦する、またはエージェント同士の対戦を見る
- 自分対エージェントでは、黒（先手）か白（後手）を選ぶ
- 打てるマスと、直前の手が印で分かる
- 終局後に勝敗と石数を確認し、カタログへ戻る

同時に進行できる対局は 1 局です。人間同士の対戦、ランキング、観戦配信はありません。リバーシの公式ルールを知らなくても、合法手の印を見て打てます。

## 必要なもの

- 個人用のパソコン（目安としてメモリ 16 GiB まで）
- [Podman](https://podman.io/)
- [podman-compose](https://github.com/containers/podman-compose)（Python。起動の正はこちら。プラグインの `podman compose` は本リポジトリの external secret を扱えない）
- [mkcert](https://github.com/FiloSottile/mkcert)（ブラウザ向けの証明書）
- Google Chrome
- （「生成 AI (Jev)」と対局する場合）[OpenRouter](https://openrouter.ai/) の API キー

## 準備（最初の一度だけ）

このリポジトリを手元に置き、そのディレクトリで次を実行します。

```bash
mkcert -install
mkdir -p data/certs
mkcert -cert-file data/certs/cert.pem -key-file data/certs/key.pem 127.0.0.1
```

続けて Podman secret を作ります。起動に必要です。生成 AI を使うときは OpenRouter の API キーを、使わないときは空でない適当な文字列を、標準入力から渡します。

```bash
podman secret create openrouter-api-key-reversi -
```

1Password CLI を使う場合は以下のとおりです。

```bash
op item get 'OpenRouter API Key - reversi' --field '認証情報' --reveal | podman secret create openrouter-api-key-reversi -
```

入力したあと、改行して Ctrl+D で確定します。API キーをリポジトリや `.env` に置かないでください。

## 起動する

対局と学習の運用コマンドの正本はこの README です。試験・lint・E2E は [CONTRIBUTING.md](CONTRIBUTING.md)、配置と層は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) です。

```bash
podman-compose up --build web strategy
```

学習用の `train` は上げません。学習し直す手順は後述です。

Google Chrome で次を開きます。

```text
https://127.0.0.1:3000/
```

このパソコン以外からはつながりません。証明書の警告が出るときは、準備の `mkcert -install` が済んでいるかを確認してください。

止めるときは次を実行します。

```bash
podman-compose down
```

## 対局する

1. カタログ画面で、各エージェントの表示名と説明を読む。カテゴリは小さく併記される。
2. **対局モード** を選ぶ（画面上部のセグメント）。
   - **利用者対エージェント**: 石ボタンで自分の色を選び、カードをクリックして相手を 1 体選ぶ。`<select>` は無い。
   - **エージェント対エージェント**: 先に **黒スロット** か **白スロット** を選び、カードで埋める（同じエージェントでもよい）。**着手間隔（秒）** を変えられる。未変更時は 1 秒。開始後は終局まで自動で進む。
3. 画面下部の対戦の要約（例: あなた・黒 vs ルールベース (ミニマックス)）を確認し、**対局を開始** を押すと盤面画面へ移る。要約と開始はスクロールしても使える。

### 盤面の操作

左に大きな盤、右に対局情報を横並びに出す（Google Chrome 前提）。黒と白それぞれに石・表示名・公式石数があり、手番側が強調される。

- 自分の手番では、印の付いた合法手のマスをクリックする。印の無いマスは選べない。
- 合法手がなくパスが必要なときは、盤の近くの **パス** を押す。
- 直前に置かれた石は、他のマスと区別できる印が付く。
- 座標はファイル a–h、ランク 1–8 である（黒から見て a1 が左下）。
- 終局、または続けられない状態になると、勝敗バナーが出て **カタログへ戻る** が使える。
- 盤面にカタログ一覧や相手選択は無い。

エージェント対エージェントでは、着手の入力は不要です。1 手が盤に適用されてから次の 1 手が適用されるまで、設定した着手間隔以上空きます。未変更時は 1 秒です。間隔を渡さない API 対局は、これまでどおり速く終局します。

「生成 AI (Jev)」は、有効な OpenRouter の API キーが無いと対局を続けられません。その場合は画面にその旨が出ます。

## API だけで対局する

画面を使わず、起動済みのサービスへ HTTPS で問い合わせても対局できます。入口は `https://127.0.0.1:3000` です。戦略プロセスのポートへはつながません。証明書は mkcert なので、curl では `-k` を付けます。

対局の作成と着手は POST です。ヘッダ `Origin: https://127.0.0.1:3000` が無いと 403 になります。カタログと盤面の GET には Origin は不要です。同時に進行できる対局は 1 局で、新しく始めると進行中の局は置き換わります。

カタログ（個体 ID は `specimen_id`）:

```bash
curl -sk https://127.0.0.1:3000/api/catalog
```

利用者対エージェント（自分が黒、相手はランダム）:

```bash
curl -sk https://127.0.0.1:3000/api/games \
  -H 'Origin: https://127.0.0.1:3000' \
  -H 'Content-Type: application/json' \
  -d '{"black":{"kind":"human"},"white":{"kind":"specimen","specimen_id":"random_uniform"}}'
```

応答の `id` が対局 ID です。着手と盤面の確認:

```bash
curl -sk https://127.0.0.1:3000/api/games/<対局ID>

curl -sk https://127.0.0.1:3000/api/games/<対局ID>/moves \
  -H 'Origin: https://127.0.0.1:3000' \
  -H 'Content-Type: application/json' \
  -d '{"type":"place","square":"f5"}'
```

パスするときは `{"type":"pass"}` を送ります。違法な手は盤に載らず、409 でその旨が返ります。

エージェント対エージェント（開始後は終局まで自動で進みます。盤面は GET で確認します。`move_interval_seconds` を付けると、1 手の適用から次の適用までその秒数以上空きます。省略時は待たず速く終局します）:

```bash
curl -sk https://127.0.0.1:3000/api/games \
  -H 'Origin: https://127.0.0.1:3000' \
  -H 'Content-Type: application/json' \
  -d '{"black":{"kind":"specimen","specimen_id":"minimax"},"white":{"kind":"specimen","specimen_id":"rl"}}'
```

自分が白のときは `black` に個体、`white` に `{"kind":"human"}` を置きます。

## カタログのエージェント

初版で選べる相手は次のとおりです。方針の詳細は [docs/catalog/](docs/catalog/) の解説 Markdown を見てください。カタログ画面の説明文は短い要約です。

| 表示名 | 概要 | 解説 |
| --- | --- | --- |
| ランダム (一様) | 合法手を等確率で選ぶ | [docs/catalog/random_uniform.md](docs/catalog/random_uniform.md) |
| ルールベース (最多取り) | いちばん多く裏返す手を選ぶ | [docs/catalog/most_flips.md](docs/catalog/most_flips.md) |
| ルールベース (位置評価) | マスの点数合計がいちばん高い手を選ぶ | [docs/catalog/positional.md](docs/catalog/positional.md) |
| ルールベース (ミニマックス) | 先を読んで位置評価する | [docs/catalog/minimax.md](docs/catalog/minimax.md) |
| ルールベース (αβ) | 深さ 4 の Negamax。葉は Mobility・角・石差 | [docs/catalog/alphabeta.md](docs/catalog/alphabeta.md) |
| ルールベース (定石) | 短い定石に乗り、外れたら位置評価する | [docs/catalog/opening.md](docs/catalog/opening.md) |
| 機械学習 (棋譜) | 対局前に学習したモデルで着手する | [docs/catalog/ml.md](docs/catalog/ml.md) |
| 機械学習 (LightGBM) | 対局前に LightGBM で学習したモデルで着手する | [docs/catalog/lgbm.md](docs/catalog/lgbm.md) |
| 強化学習 (自己対局) | 自己対局で得た方針で着手する | [docs/catalog/rl.md](docs/catalog/rl.md) |
| ニューラルネットワーク (棋譜) | 対局前に学習したネットワークで着手する | [docs/catalog/nn.md](docs/catalog/nn.md) |
| 生成 AI (Jev) | OpenRouter 上の Jev が合法手から選ぶ | [docs/catalog/jev.md](docs/catalog/jev.md) |

学習し直さなくても、これらの相手とは対局できます。自分で学習し直す手順は次節です。基準の総当たり結果は [docs/benchmarks/round-robin.md](docs/benchmarks/round-robin.md) です（数値の正本は JSON）。勝ち点の推移は [docs/benchmarks/history.md](docs/benchmarks/history.md) です。その成績は JSON の `git.blobs` が指す学習成果物に対する記録であり、いまの `models/` と blob が異なれば一致しません。取り直すときは、対局サービスを起動したうえで次を実行します。

```bash
python3 docs/benchmarks/round_robin.py
python3 docs/benchmarks/render.py
```

ホストの Python は OpenRouter の鍵を持ちません。生成 AI (Jev) の鍵は戦略コンテナだけが読みます。CI では走らせません。

## 学習し直す（任意）

対局用の `strategy` ではなく、学習用サービスを待ち受けせず一発起動します。実行時に `uv sync` はしません。ホストの `uv run` は学習の正ではありません。専用 GPU は不要です。

**機械学習 (棋譜)**、**機械学習 (LightGBM)**、**ニューラルネットワーク (棋譜)** は、[WTHOR](https://www.ffothello.org/informatique/la-base-wthor) の 8×8 棋譜（`.wtb`）と、終局して残った自対局（`data/games.sqlite`）を使います。WTHOR の ZIP を手元で展開し、拡張子が `.wtb` のファイルを `data/wthor/` の直下に置いてください。ファイル名は問いません（例: `2024.wtb`、`2025.wtb`）。置いた `.wtb` をすべて読みます。このリポジトリから原本は配りません。再配布しないでください。

**強化学習 (自己対局)** は自己対局だけで学びます。WTHOR は使いません。

```bash
mkdir -p data/wthor

podman-compose run --rm train python -m reversi.train.ml \
  --wthor /data/wthor --games /data/games.sqlite --out /models/ml.json

podman-compose run --rm train python -m reversi.train.lgbm \
  --wthor /data/wthor --games /data/games.sqlite --out /models/lgbm.txt

podman-compose run --rm train python -m reversi.train.rl \
  --out /models/rl.json

podman-compose run --rm train python -m reversi.train.nn \
  --wthor /data/wthor --games /data/games.sqlite --out /models/nn.onnx
```

書き出したファイルを、すでに動いている対局が読むなら、サービスを起動し直してください。

```bash
podman-compose down
podman-compose up --build web strategy
```

## 他の生成 AI を足す（任意）

OpenRouter 上の別モデルをカタログに足すときは、`data/config.toml` にモデル名と呼称とパラメータを書きます。対局画面から足す操作はありません。プロンプト本文は `prompts/` のファイルから読みます。

```toml
[[generative_ai]]
model = "openrouter-上のモデルID"
name = "呼称"
temperature = 0.0
```

カタログには「生成 AI (呼称)」のように表示されます。呼称はカタログ内で重複してはいけません。応答は JSON として検証し、合法手の外や検証失敗は着手に採用しません。ファイルを書いたあと、カタログ画面を開き直してください。一覧に現れないときはサービスを起動し直してください。

## 開発に参加する場合

ブランチ命名、コミット規約、試験・lint・ホットリロードは [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。
