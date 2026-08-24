# CoreS3 ファームウェア

PC 側が頭脳で、この機体は入出力の端末です。

```
PC → 音声(PCM) と 表情(state)
PC ← マイク(PCM) / タッチ / 加速度センサ
```

**マイクとスピーカーは I2S を共有していて同時には開けません。** そのため
喋っているあいだは耳を閉じる半二重で切り替えます（`mic_in.cpp`）。
音響エコーは構造的に起きない代わりに、音声での barge-in はできません。
詳細は [ロボットのマイクで聞く](../docs/core-mic.md)。

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

1. PC 側を起動する

   ```powershell
   .venv\Scripts\python -m pc.main
   ```

   既定（`audio.output: coreS3`）ではウサギからだけ音が出ます。PC でも
   同時に聴きたいときは `--serve` を付けるか、設定を `both` にします。

2. CoreS3 の電源を入れる

接続されると画面の `PC not connected` が消えます。あとは PC に話しかければ、
ウサギから声が出ます。

実機がないときは `tools/dummy_core.py` が代わりになります。

## 画面の見かた

| 表示 | 意味 |
|---|---|
| 目が上を向く | 考え中 |
| 口が動く | 喋っている（音量に連動） |
| 背景色 | 感情（喜=緑 / 困=黄 / 驚=赤 / 普=青） |

### 開発モードと製品モード

**画面より下、映像が出ていない部分の中央を触ると切り替わります。**
起動時は開発モードです。

| | 開発モード | 製品モード |
|---|---|---|
| 状態のラベル（idle など） | 出る | 出ない |
| `PC not connected` | 出る | 右上に小さな橙の点だけ |
| 下端の `DEV - tap below the screen` | 出る | 出ない |

製品モードでも同じ場所を触れば開発モードに戻れます。案内が消えるだけで、
ボタンは生きています。

**CoreS3 に押しボタンはありません。** ただしタッチ面は画面より下まで続いて
いて、その見えない帯が `BtnA` / `BtnB` / `BtnC`（左・中央・右）になっています。
モード切替に使っているのは中央の `BtnB` です。

`M5.setTouchButtonHeight()` は「画面の下端から何 px をボタン側に広げるか」で、
**0 のまま使います**（`TOUCH_BUTTON_HEIGHT`）。値を与えると顔の下の部分を
触ってもボタンが押されてしまいます。

画面はすべて PC へ touch イベントとして飛びます。ボタンの帯は飛びません
（`main.cpp` の `pollTouch`）。

## 構成

| ファイル | 役割 |
|---|---|
| `main.cpp` | 全体の流れ、タッチと加速度センサ |
| `config.h` | 公開してよい設定 |
| `secrets.local.h` | WiFi 認証情報（**非公開**） |
| `net.cpp` | WiFi と WebSocket、プロトコルの処理 |
| `mic_in.cpp` | マイク録音と半二重の切り替え |
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
| PC → | text | `{"t":"mic","on":true/false,"rate":16000}` |
| → PC | text | `{"t":"hello","fw":"...","mic":true}` |
| → PC | binary | マイクの PCM（16kHz mono s16le / 512 サンプル） |
| → PC | text | `{"t":"touch","x":..,"y":..}` |
| → PC | text | `{"t":"imu","event":"lift"}` |
| → PC | text | `{"t":"audio_done"}` |

## 設計上の判断

**プリバッファ 200ms。** Wi-Fi のゆらぎを吸収します。長くすると途切れにくく
なりますが、鳴らし切るまでマイクを開けないので「喋り終わってから聞けるまで」が
その分だけ延びます。

**リングバッファは PSRAM に置いています。** 内蔵 RAM は画面と WiFi に使いたい
ためです。溢れたときは古い方を捨てて追いつきます（遅延を溜めない）。

**口パクは CoreS3 側で計算しています。** PC 側で計算して送るより、実際に
鳴らしているバッファを見るほうが同期が正確です。

**顔はスプライト（M5Canvas）に描いてから画面へ送っています。** 画面へ直接
描くと「消してから描き直すまで」が見えてちらつくためです。スプライトは
PSRAM に置いています（150KB）。内蔵 RAM なら DMA が使えて速いのですが、
WiFi と音声のぶんを削ってまで取りにいく価値はないと判断しました。

**送るのは変わった場所だけです。** 全画面は 320x240x2 = 150KB あり、SPI
40MHz でも 30ms 以上かかります。**マイクの録音バッファを積み直す猶予は
512 サンプル x 2 枚 = 64ms しかない**ので、口が動くたびに全画面を送ると
マイクの音が欠けます。`setClipRect()` で範囲を絞ってから `pushSprite()`
すると、LovyanGFX は範囲内の画素だけを転送します。

全画面を送るのは state / emotion が変わったときだけで、そのときマイクは
PC の指示で閉じているので噛み合っています。1フレームが
`FACE_SLOW_FRAME_MS`（既定 40ms）を超えたらシリアルに出ます。

**マイクを開くかどうかは、PC の指示より「いま鳴っているか」を優先します。**
指示の行き違いでスピーカーとマイクが同時に開くと、どちらも壊れるためです。

**録音バッファは3枚で回しています。** M5Unified は録音要求を2枚まで先行して
受けるので、`record()` が戻った時点で「2つ前の1枚」は録り終わっていますが、
2枚だとその1枚を次の `record()` が上書きしてしまいます。
