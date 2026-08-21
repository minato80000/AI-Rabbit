# CoreS3 ファームウェア（Step 3）

PC 側が頭脳で、この機体は入出力の端末です。

```
PC → 音声(PCM) と 表情(state)
PC ← タッチ / 加速度センサ
```

音声入力は PC のマイクを使うため、この機体では扱いません。CoreS3 は
マイクとスピーカーが I2S を共有していて同時使用に制約があるので、
入力を PC に逃がしたこの構成なら、その問題を避けられます。

## 必要なもの

- M5Stack CoreS3
- PlatformIO（VS Code 拡張に同梱のものが使えます）

## 設定

WiFi の認証情報を書きます。

```powershell
copy firmware\src\secrets.local.h.example firmware\src\secrets.local.h
```

コピーしたファイルに自分の WiFi と PC の IP を書いてください。

```c
#define WIFI_SSID     "..."
#define WIFI_PASSWORD "..."
#define PC_HOST       "192.168.0.2"   // PC の IP。ipconfig で確認
```

`secrets.local.h` は `.gitignore` と pre-commit フックの**二重**で保護されており、
`git add -f` で強制的にステージしてもコミットが止まります。

## ビルドと書き込み

```powershell
cd firmware
pio run                  # ビルドだけ（実機なしでも通ります）
pio run -t upload        # 書き込み
pio device monitor       # シリアルを見る
```

PlatformIO の CLI が PATH にない場合は、VS Code 拡張に同梱のものを使えます。

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run
```

## 動かす

1. PC 側を `--serve` 付きで起動する

   ```powershell
   .venv\Scripts\python -m pc.main --serve
   ```

2. CoreS3 の電源を入れる

接続されると画面の `PC not connected` が消えます。あとは PC に話しかければ、
ウサギから声が出ます。

実機がないときは `tools/dummy_core.py` が代わりになります。

## 画面の見かた

いまは Step 4 の顔を作り込む前なので、状態が分かる最小限の表示です。

| 表示 | 意味 |
|---|---|
| 左上の文字 | 現在の状態（idle / listening / thinking / speaking） |
| `PC not connected` | PC に繋がっていない |
| 目が上を向く | 考え中 |
| 口が動く | 喋っている（音量に連動） |
| 背景色 | 感情（喜=緑 / 困=黄 / 驚=赤 / 普=青） |

## 構成

| ファイル | 役割 |
|---|---|
| `main.cpp` | 全体の流れ、タッチと加速度センサ |
| `config.h` | 公開してよい設定 |
| `secrets.local.h` | WiFi 認証情報（**非公開**） |
| `net.cpp` | WiFi と WebSocket、プロトコルの処理 |
| `audio_out.cpp` | リングバッファ → スピーカー |
| `face.cpp` | 状態に応じた画面表示 |

## プロトコル

PC 側の仕様は `tools/protocol_test.py` が固定しています。
変更するときは、あちらのテストも合わせて更新してください。

| 向き | 種別 | 内容 |
|---|---|---|
| PC → | text | `{"t":"state","v":"...","emotion":"..."}` |
| PC → | text | `{"t":"audio_begin","rate":24000,"ch":1,"fmt":"s16le"}` |
| PC → | binary | PCM チャンク |
| PC → | text | `{"t":"audio_end"}` / `{"t":"audio_flush"}` |
| → PC | text | `{"t":"hello","fw":"..."}` |
| → PC | text | `{"t":"touch","x":..,"y":..}` |
| → PC | text | `{"t":"imu","event":"lift"}` |
| → PC | text | `{"t":"audio_done"}` |

## 設計上の判断

**プリバッファ 100ms。** Wi-Fi のゆらぎを吸収します。長くすると途切れにくく
なりますが、barge-in で黙るまでが鈍くなります。

**リングバッファは PSRAM に置いています。** 内蔵 RAM は画面と WiFi に使いたい
ためです。溢れたときは古い方を捨てて追いつきます（遅延を溜めない）。

**口パクは CoreS3 側で計算しています。** PC 側で計算して送るより、実際に
鳴らしているバッファを見るほうが同期が正確です。
