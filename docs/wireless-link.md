# WiFi ルータなしで繋ぐ

最終更新: 2026-08-25

## 決定

| 項目 | 決定 |
|---|---|
| 既定 | **PC のモバイルホットスポット**（`hotspot`）。ルータ不要でネットも保てる |
| 持ち出す用 | **ロボットが親機**（`robot-ap`）。ルータもネットも要らない |
| 従来 | 家の WiFi ルータ（`router`）。残してある |
| USB / Bluetooth | 採らない（[理由](#採らなかった案)） |
| 実機での確認 | **`hotspot` は通した**（2026-08-25）。`robot-ap` は PC 側の接続が未確認 |

**プロトコルは3通りとも同じ。** 変わるのは電波の親機を誰にするかと、
WebSocket をどちらが待ち受けるかだけ。音声も state もセンサも、
[対話システムの設計](dialogue-system.md#pc--cores3-プロトコル)のまま動く。

---

## 帯域が選択肢を決めた

繋ぎ方を選ぶ前に、何 bps 要るのかを出しておく。ここで大半の案が落ちる。

| 向き | 内容 | 帯域 |
|---|---|---|
| PC → CoreS3 | 24kHz / 16bit / mono | 384 kbps |
| CoreS3 → PC | 16kHz / 16bit / mono | 256 kbps |

**この2つは同時に流れない。** マイクとスピーカーは I2S を共有していて同時に
開けないので、喋るあいだ耳は閉じている（[半二重](core-mic.md)）。
つまり必要なのは **一方向 384 kbps** で、合計 640 kbps ではない。

384 kbps を切らずに出せるか——これが可否を分ける線になる。

---

## 3通りの比較

| | `router` | `hotspot` | `robot-ap` |
|---|---|---|---|
| 親機（電波を出す） | 家の WiFi ルータ | **PC** | **CoreS3** |
| WebSocket | PC が待つ | PC が待つ | **PC が繋ぎに行く** |
| ルータ | **要る** | 不要 | 不要 |
| インターネット | 要らない | **PC 側に要る**（後述） | 要らない |
| PC のネット接続 | 保てる | 保てる | **落ちる** |
| 接続先アドレス | ipconfig で調べる | 192.168.137.1 固定 | 192.168.4.1 固定 |
| ファイアウォール | 規則が要ることがある | 実測では不要（[後述](#ファイアウォールは要らなかった)） | 要らない |
| ファーム | `LINK_STA` | `LINK_STA` | `LINK_ROBOT_AP` |

### どちらを使うか

**家では `hotspot`。** PC のインターネットが保てるので開発中に困らない。
ルータが要らないので、繋ぎ先が変わっても設定を書き直さずに済む。

**持ち出すなら `robot-ap`。** Windows のモバイルホットスポットは
**共有できるインターネット接続がないと入れられない**ので、ネットの無い場所では
使えない。ロボット自身が親機になればその制約が消える。

`router` は従来の繋ぎ方で、動いているものを壊さないために残してある。

### アドレスが固定なのが効く

`router` では PC の IP を `ipconfig` で調べ、`secrets.local.h` に書いて
焼き直す必要がある。DHCP で変わればまた焼く。

残り2つはアドレスが決まっている。

- **192.168.137.1** — Windows のホットスポットは共有アダプタにこの
  アドレスを使う。ずっとこの値
- **192.168.4.1** — ESP32 の SoftAP はゲートウェイに必ずこのアドレスを使う

どちらも既定値に入れてあるので、**IP を調べる作業そのものが無くなる。**

---

## 使う

### A. PC のホットスポット（`hotspot`）

**1. ホットスポットを入れて、SSID とパスワードを見る**

```powershell
.\tools\hotspot.ps1 -Action Start
```

SSID・パスワード・帯域・ファイアウォールの状態がまとめて出る。
`-Action Status` なら状態を見るだけ、`-Action Stop` で切れる。

**2. ファームに書いて焼く**

`firmware/src/secrets.local.h` に、1 で出た値をそのまま貼る。

```c
#define WIFI_SSID     "PC のホットスポットの SSID"
#define WIFI_PASSWORD "そのパスワード"
```

`PC_HOST` は書かなくてよい（既定が 192.168.137.1）。

```powershell
cd firmware
pio run -t upload
```

**3. PC 側**

`pc/config.yaml` は既定でこの構成になっている。

```yaml
transport:
  link: "hotspot"
```

```powershell
.venv\Scripts\python -m pc.main
```

#### 帯域は 2.4GHz にすること

**CoreS3（ESP32-S3）は 2.4GHz しか受けられない。** ホットスポットが 5GHz で
立っていると SSID がそもそも見えず、設定が合っていても繋がらない。

`hotspot.ps1 -Action Status` が帯域を出すので、`TwoPointFourGigahertz` 以外なら
設定 > ネットワークとインターネット > モバイル ホットスポット の
「使用する帯域」を 2.4 GHz にする。**「任意で利用可能」(Auto) でも 5GHz を
掴むことがある**ので、明示しておくほうが確実。

### B. ロボットが親機（`robot-ap`）

**1. ファームに AP の設定を書いて焼く**

`firmware/src/secrets.local.h`:

```c
#define LINK_MODE   LINK_ROBOT_AP
#define AP_SSID     "UsachanRobo"
#define AP_PASSWORD "8文字以上のパスワード"
```

**パスワードが8文字未満だと WPA2 にできず、暗号化なしの AP になる**
（起動時にシリアルへ警告が出る）。

```powershell
cd firmware
pio run -e robot-ap -t upload
```

`secrets.local.h` を書き換えなくても、環境を分けてあるので
`-e robot-ap` を付けるだけで AP 版が焼ける。ビルドディレクトリも別なので、
`-e m5stack-cores3` に戻せば元の構成に戻る。

**2. ロボットの電源を入れ、PC の WiFi をその SSID に切り替える**

シリアル（`pio device monitor`）に出る。

```
[net] AP "UsachanRobo" ch6 WPA2 / 192.168.4.1
[net] PC の WiFi をこの SSID に切り替えてください
[net] 待ち受け ws://192.168.4.1:8765/rabbit
```

**この間 PC はインターネットに出られない。** Ollama も VOICEVOX も whisper も
ローカルなので対話そのものは動くが、調べ物はできなくなる。

**3. PC 側**

```yaml
transport:
  link: "robot-ap"
```

```powershell
.venv\Scripts\python -m pc.main
```

ロボットが落ちても PC 側は繋ぎ直しに行くので、実機の電源を入れ直しても
PC を起動し直す必要はない。

### C. 家の WiFi ルータ（`router`・従来）

```c
#define WIFI_SSID     "家の WiFi 名"
#define WIFI_PASSWORD "そのパスワード"
#define PC_HOST       "192.168.0.2"   // ipconfig で調べる
```

```yaml
transport:
  link: "router"
```

ファーム側は `hotspot` と同じ `LINK_STA` で、`pio run -t upload` のまま。
**ファームからはルータかホットスポットかを区別できない**（どちらも
「既にある AP に参加して PC へ繋ぎに行く」）。名前を分けてあるのは、
PC の IP の調べ方と、電波を誰が出しているかが人間側で違うため。

---

## 実機なしで試す

`robot-ap` では**待ち受けるのがロボット側**になるので、ダミーも向きを
変える必要がある。`--serve` がその役をする。

```powershell
# ロボット役（待ち受ける）
.venv\Scripts\python tools\dummy_core.py --serve

# PC 側。config.yaml を link: robot-ap / core_host: "127.0.0.1" にして
.venv\Scripts\python -m pc.main --text "こんにちは"
```

従来どおり PC が待ち受ける構成（`router` / `hotspot`）なら `--serve` は不要。

自己テストは両方の向きを見る。

```powershell
.venv\Scripts\python tools\protocol_test.py    # 27項目（うち11項目が robot-ap）
```

---

## 採らなかった案

### USB（有線）

**帯域だけなら一番よい。** CoreS3 の USB-C は ESP32-S3 のネイティブ USB に
繋がっていて、CDC で数 Mbps 出る。384 kbps に対して桁違いの余裕があり、
ジッタもほぼ無く、給電も兼ねるのでバッテリ切れが無くなる。
プリバッファ 200ms を削れる見込みもあった。

**採らなかったのは有線になるから。** 卓上ロボットとして線が生えるのは
体験が変わる。無線のまま router 依存だけを外せる方法があったので、そちらを
選んだ。帯域か安定性で行き詰まったときの次の手として残しておく。

### Bluetooth（BLE）

**ESP32-S3 に Bluetooth Classic は無い。** BLE 5.0 だけなので SPP は使えない。

BLE の実効帯域は Windows のホストスタックでおおむね 100〜300 kbps で、
**384 kbps に届かない。** 音声を ADPCM で圧縮するか再生を 16kHz に落とせば
入るが、実装量が最も大きく、音質も落ちる。得るものが「WiFi ではない」だけ
なので割に合わない。

### ESP-NOW

ルータ無しで ESP32 同士を繋ぐ仕組みだが、**PC は ESP-NOW を喋れない。**
USB に ESP32 のドングルを挿して中継させることになるが、そこまでやるなら
その USB で直接繋いだほうが速くて単純。

なお ESP-NOW も SoftAP も**電波としては WiFi のまま**で、外れるのは
ルータへの依存だけ。今回の狙いはそこだった。

---

## 仕組み

### プロトコルは変えていない

[対話システムの設計](dialogue-system.md#pc--cores3-プロトコル)のまま。
フレームも意味も同じで、**変わるのは誰が待ち受けるかだけ。**

### PC 側

繋ぐ向きに依らない部分を `pc/transport/link.py` の `RabbitLink` に置き、
待ち受ける／繋ぎに行くの一点だけを分けてある。

| ファイル | 役割 |
|---|---|
| `transport/link.py` | プロトコル・音声・state・センサ。**向きに依らない全部** |
| `transport/server.py` | `RabbitServer` — 待ち受ける（`router` / `hotspot`） |
| `transport/client.py` | `RabbitClient` — 繋ぎに行く（`robot-ap`）。再接続つき |
| `transport/__init__.py` | `build_link(cfg)` — 設定から組み立てる |

繋がったあとの1本を回すのは `RabbitLink._serve_connection()` で、
どちらの向きでも同じコードを通る。`main.py` から見えるのは `RabbitLink` だけ
なので、**接続の向きが変わっても対話ループ側は何も変わらない。**

### ファーム側

`config.h` の `LINK_MODE` で切り替える。

| | `LINK_STA`（既定） | `LINK_ROBOT_AP` |
|---|---|---|
| WiFi | `WiFi.begin()` で AP に参加 | `WiFi.softAP()` で自分が AP |
| WebSocket | `WebSocketsClient` | `WebSocketsServer` |
| 再接続 | ライブラリ任せ + WiFi 監視 | PC が繋ぎ直しに来る |

`net.cpp` は `#if` で使うほうだけを取り込む。両方積むとメモリが惜しいため。
**`WStype_*` イベントの処理から下は共通**で、`hello` を返すのも、
`audio_begin` を受けるのも、マイクの PCM を送るのも同じコードを通る。

待ち受ける側では接続先のパス（`/rabbit`）を `WStype_CONNECTED` の payload で
受け取れるので、PC 側のサーバと同じように検査して弾いている。

---

## 実機で測った（2026-08-25）

CoreS3 実機（MAC `24:58:7c:e9:31:a8`）で `hotspot` を通した。

| 確認したこと | 結果 |
|---|---|
| ファームのビルド（両モード） | 成功。`m5stack-cores3` / `robot-ap` |
| プロトコル自己テスト | 27/27 合格（うち 11 項目が `robot-ap` の向き） |
| マイク側の自己テスト | 15/15 合格 |
| **ホットスポットへの接続** | **成功。`192.168.137.158` を取得** |
| **PC への WebSocket 接続** | **成功。1.3〜3.8 秒で接続し `hello` が届く** |
| **音声（PC → ロボット）** | **成功。1.0 秒ぶんを 1.11 秒で送出し `audio_done` が返る** |
| **音声（ロボット → PC）** | **成功。1024 bytes/frame が 244 枚、8.0 秒で 7.81 秒ぶん** |
| `robot-ap` の AP | 立つ。`UsachanRobo` ch6 / `192.168.4.1` / WS 待ち受けまで |

**`PC_HOST` を一度も書いていない。** シリアルにそのまま出る。

```
[net] WiFi 接続中: LAPTOP-XXXX
[net] WiFi 接続 192.168.137.158
[net] 接続先 ws://192.168.137.1:8765/rabbit   ← config.h の既定値のまま
```

### ジッタは小さかった

マイクの到着間隔（16kHz / 512 サンプル = 32ms ごとに届くはず）:

| | 実測 |
|---|---|
| 中央 | 31ms |
| 最大 | **47ms** |

**最大でも 47ms。** プリバッファ 200ms・リングバッファ 1000ms に対して
十分に余裕がある。PC の1枚のアダプタが親機と子機を兼ねる構成なので
ルータ経由より条件が悪いと踏んでいたが、そうはならなかった。

**バッファを浅くする余地がある。** `dma_buf_count` を 16 → 8 に戻す判断
（[再開の手引き](dialogue-system.md#次回まず確認すること)）は、この数値なら
試してよさそう。ただし途切れは長時間動かさないと出ないので、**ここは
まだ「短時間で問題が出なかった」以上のことは言えない。**

### ファイアウォールは要らなかった

**規則を足さずに繋がった。** ホットスポットで生える仮想アダプタは
`Get-NetConnectionProfile` に現れず、プロファイル別の受信ブロックが
当たらないため。

当初「規則が要る」と書いていたが、実測は逆だった。**まず何もせずに試すこと。**
ロボットは AP に繋がっているのに WebSocket が繋がらない、という状態に
なったときだけ `-Action Firewall` を使えばよい。

    .\tools\hotspot.ps1 -Action Firewall     # 管理者。要るときだけ

### ホットスポットは勝手に切れる

**接続する機器が無い状態が続くと、Windows がホットスポットを自動で切る。**
実際、ロボットのファームを焼き替えている間に切れていた。

そうなるとロボットは戻る先を失うので、電源を入れ直しても繋がらない。
`hotspot.ps1 -Action Status` が `Off` を返したらこれ。`-Action Start` で戻る。

毎回困るなら、設定 > ネットワークとインターネット > モバイル ホットスポット の
「電力を節約する」をオフにしておく。

## まだ測っていないこと

1. **`robot-ap` で PC が実際に繋がるか。** ロボット側は AP が立ち
   （`192.168.4.1` で WS 待ち受けまでシリアルで確認）、PC 側の
   クライアント経路も自己テストで通っているが、**両者を繋いだ実測はまだ。**
   検証に使った PC は Wi-Fi が1枚しかなく、ロボットの AP に繋ぎ替えると
   作業そのものができなくなるため見送った。試すときは
   `pio run -e robot-ap -t upload` して PC の WiFi を切り替える
2. **`robot-ap` で ESP32 の SoftAP が 384 kbps を捌けるか。**
   ルータ経由と違い、ESP32 自身が AP として TCP を終端し、CPU も音声処理と
   共用する。**ここが一番読めない。** `hotspot` のジッタ（最大 47ms）は
   参考にならない
3. **長時間の安定性。** 上の数値はどれも数秒〜数十秒の観測でしかない。
   途切れや再接続の頻度は、実際に会話を続けてみないと分からない

**推測せず測ること。** 2 は特に、動くかどうかを机上で決めないこと。
