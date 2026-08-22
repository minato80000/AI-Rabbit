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
  #define WIFI_SSID     ""
  #define WIFI_PASSWORD ""
  #define PC_HOST       "192.168.0.2"
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

// ---- センサ --------------------------------------------------------------
// 同じ動きを何度も送らないための間隔
static constexpr uint32_t TOUCH_MIN_INTERVAL_MS = 400;
static constexpr uint32_t IMU_MIN_INTERVAL_MS = 800;

// 持ち上げ・振りの判定に使うしきい値（合成加速度 g）
static constexpr float IMU_SHAKE_G = 2.0f;
static constexpr float IMU_LIFT_G = 1.4f;

// ---- 再接続 --------------------------------------------------------------
static constexpr uint32_t WS_RECONNECT_MS = 3000;
