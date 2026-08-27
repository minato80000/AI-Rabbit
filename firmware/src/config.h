// 公開してよい設定。WiFi の認証情報は secrets.local.h に置く。
#pragma once

#include <stdint.h>

// ---- 接続先 --------------------------------------------------------------
// secrets.local.h があればそちらを使う。無ければビルドは通るが接続はしない。
// （実機を持っていない人でもビルドを確認できるようにするため）
#if __has_include("secrets.local.h")
  #include "secrets.local.h"
#else
  #warning "secrets.local.h がありません。secrets.local.h.example をコピーしてください"
#endif

// ---- 繋ぎ方 --------------------------------------------------------------
// 電波の親機をどれにするか。**PC 側（pc/config.yaml の transport.link）と
// 揃えること。** 選び方と手順は docs/wireless-link.md。
//
//   LINK_STA       既にある AP に参加する。相手が家の WiFi ルータでも
//                  PC のモバイルホットスポットでも、この機体の処理は同じ。
//                  PC が待ち受け、こちらが繋ぎに行く（PC_HOST が要る）
//
//   LINK_ROBOT_AP  この機体が親機になる。**ルータもインターネットも要らない。**
//                  こちらが待ち受け、PC が繋ぎに来る（PC_HOST は使わない）
//
// PC 側の router と hotspot はどちらも LINK_STA。違いは PC の IP の調べ方と
// ファイアウォールの要否だけで、ファームからは区別できない。
//
// 切り替えるときは secrets.local.h に書く:  #define LINK_MODE LINK_ROBOT_AP
#define LINK_STA      0
#define LINK_ROBOT_AP 1

#ifndef LINK_MODE
  #define LINK_MODE LINK_STA
#endif

// secrets.local.h に書かれていないものを埋める。
// 使わないモードの値まで書かせないため、既定値はここに置く
#ifndef WIFI_SSID
  #define WIFI_SSID     ""
#endif
#ifndef WIFI_PASSWORD
  #define WIFI_PASSWORD ""
#endif
// PC の IP（LINK_STA のときだけ使う）。既定は Windows のモバイル
// ホットスポットのアドレスで、あれは常にこの値になるので調べる必要がない。
// 家の WiFi ルータ経由（router）なら ipconfig で調べて secrets に書く
#ifndef PC_HOST
  #define PC_HOST "192.168.137.1"
#endif

// ---- この機体が親機になるとき（LINK_ROBOT_AP）----------------------------
// SSID は公開してよい。パスワードは secrets.local.h に置くこと。
// PC 側の接続先は 192.168.4.1 に固定される（ESP32 の SoftAP は
// ゲートウェイに必ずこのアドレスを使う）ので、IP を調べる作業が要らない
#ifndef AP_SSID
  #define AP_SSID "UsachanRobo"
#endif
// **8文字以上で WPA2、それ未満だと暗号化なしで立つ**（net.cpp が警告を出す）
#ifndef AP_PASSWORD
  #define AP_PASSWORD ""
#endif
// 電波が混んでいたら変える。重ならないのは 1 / 6 / 11
#ifndef AP_CHANNEL
  #define AP_CHANNEL 6
#endif
// PC 1台だけ入れる。余計な機器に入られると音の帯域を持っていかれる
#ifndef AP_MAX_CLIENTS
  #define AP_MAX_CLIENTS 1
#endif

#ifndef PC_PORT
  #define PC_PORT 8765
#endif
#ifndef WS_PATH
  #define WS_PATH "/rabbit"
#endif

// ---- ファームのバージョン ------------------------------------------------
// PC 側の hello に載せる。実機を見分けるのに使う
#define FW_VERSION "0.1.0"

// ---- 音声 ----------------------------------------------------------------
// PC 側 (pc/transport/server.py) と合わせること
static constexpr uint32_t AUDIO_SAMPLE_RATE = 24000;

// 再生を始める前に溜める量。Wi-Fi のゆらぎを吸収する。
// 長くすると途切れにくいが、barge-in で黙るまでが鈍くなる
static constexpr uint32_t PREBUFFER_MS = 200;

// リングバッファの容量。PSRAM に置く
static constexpr uint32_t RINGBUFFER_MS = 1000;

// 一度にスピーカーへ渡す量
static constexpr size_t SPEAKER_CHUNK_SAMPLES = 512;

// 鳴らすチャンネル。M5Unified は8つの仮想チャンネルを持ち、-1 を渡すと
// 空いているものが自動で選ばれる。それだと連続するチャンクが別チャンネルに
// 散らばって同時再生され、音が壊れる。1つに固定すること
static constexpr int SPEAKER_CHANNEL = 0;

// ---- マイク --------------------------------------------------------------
// この機体のマイクで聞く。マイクとスピーカーは I2S1 と BCK/WS ピンを共有して
// いて同時には開けない（M5Unified の CoreS3 定義でどちらも
// i2s_port=I2S_NUM_1 / bck=GPIO34）ので、喋る間は耳を閉じる半二重で切り替える。
// 詳細は docs/core-mic.md。
//
// PC 側 (pc/config.yaml の audio.sample_rate) と合わせること
static constexpr uint32_t MIC_SAMPLE_RATE = 16000;

// 一度に送るサンプル数。16kHz なら 512 = 32ms で、PC 側の VAD の
// 1フレームとちょうど同じ長さになる（frame_samples: 512）
static constexpr size_t MIC_FRAME_SAMPLES = 512;

// 録音バッファの枚数。M5Unified は2枚まで先行して録れるので、
// 送信中の1枚を守るには3枚要る（詳細は mic_in.cpp）
static constexpr size_t MIC_BUFFERS = 3;

// 入力の増幅。M5Unified の CoreS3 既定は 2。
// PC 側で --check-mic を見て、音が小さければここを上げる
static constexpr uint8_t MIC_MAGNIFICATION = 4;

// マイクを開いた直後は値が安定しないので、この間のフレームは捨てる
static constexpr uint32_t MIC_WARMUP_MS = 120;

// 開けなかったときに毎ループ試さないための間隔
static constexpr uint32_t MIC_RETRY_MS = 1000;

// ---- 画面 ----------------------------------------------------------------
// 顔はスプライトに描いてから画面へ送る（face.cpp）。全画面は
// 320x240x2 = 150KB あり、SPI 40MHz でも 30ms 以上かかる。
// マイクの録音バッファを積み直す猶予は 64ms しかないので、
// 変わった場所だけを送る。

// 口やまばたきの更新をこの間隔で頭打ちにする。
// state / emotion の変化は待たずに即座に描く
static constexpr uint32_t FACE_MIN_FRAME_MS = 33;  // 約 30fps

// 1フレームがこれを超えたらシリアルに出す。
// マイクの猶予を食い潰しているサインなので、出るなら描画を減らすこと
static constexpr uint32_t FACE_SLOW_FRAME_MS = 40;

// 画面の下端を「ボタン扱い」に広げる量。**0 のまま使う。**
//
// CoreS3 に押しボタンは無いが、タッチ面は画面より下まで続いていて、その
// 見えない帯が BtnA / BtnB / BtnC（左・中央・右）になっている。
// M5Unified はこの値を「画面の下端から何 px をボタン側に広げるか」として
// 使うので、0 なら画面の外だけ、40 にすると顔の下 40px を触っても
// ボタンが押されてしまう。
//
// 中央の 1/3 が BtnB で、開発モードと製品モードの切り替えに使う。
static constexpr uint16_t TOUCH_BUTTON_HEIGHT = 0;

// ---- センサ --------------------------------------------------------------
// 同じ動きを何度も送らないための間隔
static constexpr uint32_t TOUCH_MIN_INTERVAL_MS = 400;
static constexpr uint32_t IMU_MIN_INTERVAL_MS = 800;

// 持ち上げ・振りの判定に使うしきい値（合成加速度 g）
static constexpr float IMU_SHAKE_G = 2.0f;
static constexpr float IMU_LIFT_G = 1.4f;

// ---- 再接続 --------------------------------------------------------------
static constexpr uint32_t WS_RECONNECT_MS = 3000;

// WiFi を繋ぎ直す間隔。**待つのは loop の外**（net.cpp は待たない）
static constexpr uint32_t WIFI_RETRY_MS = 10000;
