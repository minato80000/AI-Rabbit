# PC 母艦側（Step 1）

話しかけると、ウサちゃんロボが VOICEVOX の声で返事をします。
Step 1 ではマイクもスピーカーも PC を使います（CoreS3 はまだ不要）。

## 必要なもの

| | 用途 | 導入 |
|---|---|---|
| Python 3.12 | 本体 | 導入済み |
| Ollama | ローカル LLM | `winget install Ollama.Ollama` |
| VOICEVOX | 音声合成 | https://voicevox.hiroshiba.jp/ からインストール |

VOICEVOX は**アプリを起動しておくだけ**で、`localhost:50021` に HTTP サーバが立ちます。
（GUI を使いたくない場合は VOICEVOX ENGINE 単体でも可）

## セットアップ

```powershell
# リポジトリ直下で
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
ollama pull qwen2.5:3b
```

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

## 設定

`config.yaml` を編集します。よく触るのは:

| 項目 | 説明 |
|---|---|
| `wake.words` | ウェイクワード。ひらがなで書く（カタカナ・漢字は自動で吸収） |
| `tts.speaker` | VOICEVOX の話者 ID。`--list-speakers` で確認 |
| `tts.speed` | 話速。1.1〜1.2 くらいがロボットらしい |
| `llm.model` | Ollama のモデル名 |
| `stt.model` | `tiny` / `base` / `small`。精度が足りなければ上げる |
| `vad.threshold` | 上げると誤検出が減り、下げると小声を拾う |

## ペルソナの調整

口調は `persona/usachan.md` **だけ**を編集します。コードは触りません。
原作のセリフ例を「セリフ例」セクションに貼るほど再現度が上がります。

## トラブル

**マイクが反応しない**
`--list-devices` で入力デバイスを確認し、`config.yaml` の `audio.input_device`
にインデックス番号か名前の一部を指定してください。

**自分の声を拾って誤動作する**
Step 1 では再生中にマイクを閉じているため、原則起きません。
それでも起きる場合は `vad.threshold` を上げてください。

**返事が遅い**
初回だけモデルのロードで数十秒かかります（2回目以降は速い）。
それ以外で遅い場合は `-v` を付けて「初音出しまで」の値を確認してください。

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
| `llm/sentence.py` | ストリームの文分割・感情タグ抽出 |
| `tts/voicevox.py` | VOICEVOX |
