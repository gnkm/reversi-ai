# Reversi AI

![CI](https://github.com/gnkm/reversi-ai/actions/workflows/ci.yml/badge.svg)

自分のパソコンのブラウザから、エージェントとリバーシ（オセロ）を対戦できるサービスです。エージェント同士の対戦を見ることもできます。

画面の言葉は日本語です。ブラウザは **Google Chrome** を使ってください。このサービスはインターネットへ公開せず、起動したパソコンの中だけで使います。アカウント登録はありません。

## できること

- カタログ（名前と説明の一覧）から、対戦相手のエージェントを個体ごとに選ぶ
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

```bash
podman-compose up --build
```

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

1. カタログ画面で、各エージェントの表示名と説明を読む。
2. **対局モード** を選ぶ。
   - **利用者対エージェント**: 自分が一方の色を持ち、選んだエージェントがもう一方を持つ。
   - **エージェント対エージェント**: **黒を担当するエージェント** と **白を担当するエージェント** をそれぞれ選ぶ（同じエージェントでもよい）。**着手間隔（秒）** を変えられる。未変更時は 1 秒。開始後は終局まで自動で進む。
3. 利用者対エージェントでは、**あなたの石色**（**黒（先手）** または **白（後手）**）と **対戦相手** を選ぶ。
4. **対局を開始** を押すと、盤面画面へ移る。

### 盤面の操作

- 自分の手番では、印の付いた合法手のマスをクリックする。印の無いマスは選べない。
- 合法手がなくパスが必要なときは **パス** を押す。
- 直前に置かれた石は、他のマスと区別できる印が付く。
- 座標はファイル a–h、ランク 1–8 である（黒から見て a1 が左下）。
- 終局、または続けられない状態になると、結果が出て **カタログへ戻る** が使える。

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

初版で選べる相手は次のとおりです。方針の詳細は、カタログ画面の説明文を見てください。

| 表示名 | 概要 |
| --- | --- |
| ランダム (一様) | 合法手を等確率で選ぶ |
| ルールベース (最多取り) | いちばん多く裏返す手を選ぶ |
| ルールベース (位置評価) | マスの点数合計がいちばん高い手を選ぶ |
| ルールベース (ミニマックス) | 先を読んで位置評価する |
| ルールベース (定石) | 短い定石に乗り、外れたら位置評価する |
| 機械学習 (棋譜) | 対局前に学習したモデルで着手する |
| 機械学習 (LightGBM) | 対局前に LightGBM で学習したモデルで着手する |
| 強化学習 (自己対局) | 自己対局で得た方針で着手する |
| ニューラルネットワーク (棋譜) | 対局前に学習したネットワークで着手する |
| 生成 AI (Jev) | OpenRouter 上の Jev が合法手から選ぶ |

学習し直さなくても、これらの相手とは対局できます。自分で学習し直す手順は次節です。基準の総当たり結果は [docs/benchmarks/round-robin.md](docs/benchmarks/round-robin.md) です（数値の正本は JSON）。その成績は JSON の `git.blobs` が指す学習成果物に対する記録であり、いまの `models/` と blob が異なれば一致しません。

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
podman-compose up --build
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
