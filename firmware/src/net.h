// WiFi と WebSocket。PC 側とのやりとりを引き受ける。
//
// CoreS3 がクライアントとして PC に接続する。PC 側の IP を固定するだけで済み、
// CoreS3 の IP を知る必要がない（DHCP でアドレスが変わっても繋がる）。
//
// やりとりする内容は tools/protocol_test.py が仕様として固定している。
#pragma once

#include <stddef.h>  // size_t
#include <stdint.h>

class Net {
 public:
  void begin();
  void update();

  bool connected() const { return connected_; }

  // センサの検知を PC へ送る
  void sendTouch(int x, int y);
  void sendImu(const char* event);

  // 鳴らし終わったことを伝える。PC 側はこれが来ない場合の推定も持っている
  void sendAudioDone();

 private:
  void connectWifi();
  void onEvent(int type, uint8_t* payload, size_t length);
  void handleText(const char* text);
  void sendJson(const char* json);

  bool connected_ = false;
  bool audio_done_pending_ = false;
  uint32_t last_attempt_ms_ = 0;
};

extern Net net;
