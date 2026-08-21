# PC 母艦側（Step 1）

話しかけると、ウサちゃんロボが VOICEVOX の声で返事をします。
Step 1 ではマイクもスピーカーも PC を使います（CoreS3 はまだ不要）。

## 必要なもの

| | 用途 | 導入 |
|---|---|---|
| Python 3.12 | 本体 | 導入済み |
| NVIDIA GPU | STT の高速化（任意） | `requirements.txt` に含まれる。無ければ CPU で動く |
| Ollama | ローカル LLM | `winget install Ollama.Ollama` |
| VOICEVOX | 音声合成 | https://voicevox.hiroshiba.jp/ からインストール |

VOICEVOX は**アプリを起動しておくだけ**で、`localhost:50021` に HTTP サーバが立ちます。
（GUI を使いたくない場合は VOICEVOX ENGINE 単体でも可）

## セットアップ

```powershell
# リポジトリ直下で
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
ollama pull qwen3:4b-instruct

# 非公開ファイルの誤コミットを防ぐフックを有効化（クローン後に一度だけ）
git config core.hooksPath tools/hooks
```

**モデルは非推論版（`-instruct`）を使ってください。** `qwen3:4b`（推論版）は
思考を止められず、生の推論が返答に混ざります。詳細は `docs/dialogue-system.md`。

## 起動

```powershell
# 通常起動（マイクで話しかける）
.venv\Scripts\python -m pc.main

# マイクを使わずに LLM + 音声合成だけ試す
.venv\Scripts\python -m pc.main --text "こんにちは"

# オーディオデバイス一覧（マイクが選ばれない時に確認）
.venv\Scripts\python -m pc.main --list-devices

# VOICEVOX の話者一覧（声を選ぶとき）
.venv\Scripts\python -m pc.main --list-speakers

# 詳細ログ（レイテンシ内訳が出る）
.venv\Scripts\python -m pc.main -v
```

## 使い方

「**ウサちゃん**」と呼びかけると反応します。

- `ウサちゃん、今日はいい天気だね` — 一発で用件まで言える
- `ウサちゃん` だけ — 「はい、なんでしょう？」と返して待つ
- 一度会話が始まったら **20秒間は呼びかけ不要**（`config.yaml` の `conversation_window_sec`）

## ペルソナの調整

**このリポジトリは public なので、ペルソナは3層に分かれています。**
起動時に上から順に連結され、そのまま system prompt になります。

| # | ファイル | 公開 | 内容 |
|---|---|---|---|
| 1 | `persona/usachan.md` | される | 誰であるか。自作の説明文のみ |
| 2 | `persona/usachan.local.md` | **されない** | 口調・セリフ例（原作由来） |
| 3 | `persona/rules.md` | される | 出力フォーマットの規則 |

原作のセリフは著作物なので 2 にだけ置きます。起動時に自動で読み込まれ、
設定変更は要りません。

```powershell
copy pc\persona\usachan.local.md.example pc\persona\usachan.local.md
```

読み込まれているかは起動ログで確認できます。

```
ペルソナ: usachan.md + usachan.local.md（ローカル専用） + rules.md
```

`usachan.local.md` は `.gitignore` と pre-commit フックの**二重**で保護されており、
`git add -f` で強制的にステージしてもコミットが止まります。

### 書くときの注意

**コメント（`<!-- -->`）の中身はプロンプトに渡りません。** テンプレートの
説明文の隣に書き足すと、丸ごと捨てられます。セリフは必ずコメントの外に
書いてください。

中身の大半がコメント内だった場合は、起動時に警告が出ます。

```
WARNING usachan.local.md: 中身の大半（745 文字）が <!-- --> の中にあり、
        プロンプトに渡りません。セリフはコメントの外に書いてください
```

### 規則を最後に置いている理由

`rules.md` は必ず最後に連結されます。小型モデルは前半の指示を忘れやすく、
守ってほしい規則ほど後ろに置くほうが効くためです。

### 感情タグが出ないときは

返事の先頭に `[喜]` `[困]` `[驚]` `[普]` のいずれかを付けさせています
（CoreS3 の表情切り替えに使う）。

**会話履歴にはタグを含めたまま保存しています。** タグを剥がした文だけを
履歴に残すと、モデルが「自分は普段タグを付けない」と学習し、数ターンで
付けなくなります。実測で付与率が 2/10 から 10/10 に変わりました。

## CoreS3 への送信（Step 2）

CoreS3 の実機がなくても、ダミークライアントでプロトコルと音声転送を試せます。

**PC 側**（サーバを有効にして起動）

```powershell
.venv\Scripts\python -m pc.main --serve
```

`--serve` は `config.yaml` の `audio.output` を `both` に上書きします
（PC のスピーカーとウサギの両方から音が出る）。恒久的に変えるなら設定側で:

| `audio.output` | 動作 |
|---|---|
| `local` | PC のスピーカーだけ（既定。Step 1 の動作） |
| `coreS3` | ウサギだけ |
| `both` | 両方。開発中はこれが便利 |

**CoreS3 の代わり**（別のターミナルで）

```powershell
.venv\Scripts\python tools\dummy_core.py
```

受け取った音声を PC のスピーカーで鳴らし、状態変化を顔文字で表示します。

```
[接続] ws://127.0.0.1:8765/rabbit
  [state] thinking  / neutral    ( ･ω･)？
  [state] speaking  / happy      ( ^ω^ )
  [audio] begin 24000Hz s16le
  [audio] end   164864 bytes / 音声 3.43s / 経過 3.56s
```

主なオプション:

| | |
|---|---|
| `--no-play` | 音を鳴らさない（受信の確認だけ） |
| `--save out.wav` | 受信した音声を保存する |
| `--touch-after 3` | 3秒後に touch イベントを送る |
| `--host 192.168.x.x` | 別マシンから繋ぐ |

**プロトコルの自己テスト**

```powershell
.venv\Scripts\python tools\protocol_test.py
```

状態 push・音声転送・barge-in・イベント・再接続・誤パス拒否を自動で確認します。
CoreS3 のファームを書くときは、この仕様に合わせてください。

## 設定

`config.yaml` を編集します。よく触るのは:

| 項目 | 説明 |
|---|---|
| `wake.words` | ウェイクワード。ひらがなで書く（カタカナ・漢字は自動で吸収） |
| `tts.speaker` | VOICEVOX の話者 ID。`--list-speakers` で確認 |
| `tts.speed` | 話速。1.1〜1.2 くらいがロボットらしい |
| `llm.model` | Ollama のモデル名。**非推論モデルであること** |
| `llm.num_ctx` | 小さいほど VRAM に載る。4GB では 2048 が実測で最速 |
| `stt.model` | `medium` 推奨（実マイクで検証済み）。`small` は速いが精度が落ちる |
| `stt.device` | `cuda` 必須級。`cpu` だと medium は数秒かかる。失敗時は自動で落ちる |
| `stt.initial_prompt` | `null` 推奨。固有名詞を足すと誤反応が増える（実測済み） |
| `wake.fuzzy_distance` | 認識のゆれを許す編集距離。`1` で取りこぼし・誤反応ともゼロ |
| `stt.beam_size` | `1` でよい。medium では `5` にしても結果が変わらなかった |
| `vad.threshold` | 上げると誤検出が減り、下げると小声を拾う |

## トラブル

**マイクが反応しない**
`--list-devices` で入力デバイスを確認し、`config.yaml` の `audio.input_device`
にインデックス番号か名前の一部を指定してください。

**自分の声を拾って誤動作する**
Step 1 では再生中にマイクを閉じているため、原則起きません。
それでも起きる場合は `vad.threshold` を上げてください。

**返事が遅い**
初回だけモデルのロードで6秒ほどかかります（2回目以降は速い）。
それ以外で遅い場合は `-v` を付けて「初音出しまで」の値を確認してください。

**返答に英語の独り言が混ざる**
推論モデルを使っています。`llm.model` を `-instruct` 版にしてください。

**名前を呼んでも反応しない**
whisper が「ウサちゃん」を「おさちゃん」と綴ることがあります。
`wake.fuzzy_distance` を `1`（既定）にしてください。`0` だと取りこぼします。
逆に `stt.initial_prompt` に固有名詞を足すと、似た音まで拾って誤反応が増えます。

**GPU で動いているか確認したい**
起動ログに `whisper loaded: base / cuda / int8_float16` と出ます。
`cpu` と出ている場合は CUDA ライブラリが見つからずフォールバックしています
（動作はしますが 8 倍遅くなります）。

## マイクの聞き取りがおかしいとき

実マイクの音は、部屋の反響・距離・マイクの癖があり、認識が崩れやすいです。
原因が「音量」「VAD の切り出し」「モデルの力不足」のどれなのかを切り分ける
診断ツールがあります。

```powershell
# 6秒録音して、音量・VAD・モデル別の認識結果をまとめて出す
.venv\Scripts\python -m pc.main --check-mic

# 長めに録りたいとき
.venv\Scripts\python -m pc.main --check-mic --seconds 10

# 録音済みファイルを解析（録り直し不要。設定を変えて何度でも試せる）
.venv\Scripts\python -m pc.main --wav recordings/mic-20260820-193000.wav
```

出力は次の4段です。

| 段 | 見るところ |
|---|---|
| 音量 | ピークが -20dBFS 前後あるか。小さすぎ・割れの警告が出ないか |
| VAD | 話した回数どおりに区間が取れているか。0本なら `vad.threshold` を下げる |
| モデル別の認識 | base / small / medium を beam=1 と 5 で比較。一番正確なものを選ぶ |
| 所要時間 | 精度と速度のバランスを見る |

録音は `recordings/` に残ります（`.gitignore` 済みなので公開されません）。

結果を見て `config.yaml` を調整してください。

| 症状 | 対処 |
|---|---|
| 音量が小さい | Windows のマイク音量を上げる。マイクに近づく |
| VAD が0本 | `vad.threshold` を 0.3 程度まで下げる |
| 語尾が切れる | `vad.hangover_ms` を 600 程度まで上げる |
| 認識が不正確 | `stt.model` を上げる（`medium` が既定。さらに上は `large-v3`） |

### Windows 側で確認すること

Windows のマイク処理が認識精度を落としていることがあります。
ノイズ抑制やエコーキャンセルは通話向けの調整で、音声認識には不利に働く場合があります。

1. タスクバーのスピーカーアイコンを右クリック →「サウンドの設定」
2. 入力デバイスを選択 →「オーディオの拡張」を**オフ**にする
3. 入力音量を 80〜100 に上げる

マイク配列（ビームフォーミング）を積んだノート PC では、正面から
30cm 程度の距離で話すのが最も安定します。

既定は `medium` です。実マイクでの実測では base が明確に崩れ、small は
惜しいところまで、medium が完璧でした。GPU なら 413ms で済み、VRAM も
LLM と合わせて 3616/4096 MiB に収まります。

## 構成

| ファイル | 役割 |
|---|---|
| `main.py` | 対話ループ本体 |
| `state.py` | 状態機械（Step 4 で CoreS3 の顔と同期させる） |
| `wake.py` | ウェイクワード判定・会話モード |
| `audio/mic.py` | マイク入力 |
| `audio/vad.py` | Silero VAD による発話区間の切り出し |
| `audio/player.py` | 再生キュー（Step 3 で CoreS3 送信に差し替え） |
| `stt/whisper.py` | faster-whisper |
| `llm/client.py` | Ollama / Claude の切り替え |
| `llm/sentence.py` | ストリームの文分割・感情タグ抽出・TTS サニタイズ |
| `tts/voicevox.py` | VOICEVOX |
