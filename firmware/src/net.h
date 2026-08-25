// WiFi と WebSocket。PC 側とのやりとりを引き受ける。
//
// 繋ぎ方は config.h の LINK_MODE で決まる。**プロトコルはどちらでも同じで、
// 違うのは「どちらが待ち受けるか」だけ。**
//
//   LINK_STA       既にある AP（家のルータ / PC のホットスポット）に参加し、
//                  こちらから PC へ繋ぎに行く。PC の IP を固定するだけで済み、
//                  こちらの IP を知らせる必要がない
//
//   LINK_ROBOT_AP  この機体が親機になり、こちらが待ち受けて PC が繋ぎに来る。
//                  ルータもインターネットも要らず、接続先は 192.168.4.1 固定
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

  // マイクで拾った PCM をそのまま PC へ流す。s16le mono
  void sendMicFrame(const int16_t* data, size_t samples);

 private:
  void connectWifi();  // LINK_STA: 既にある AP に参加する
  void startAp();      // LINK_ROBOT_AP: 自分が親機になる
  void onEvent(int type, uint8_t* payload, size_t length, uint8_t client = 0);
  void handleText(const char* text);
  void sendJson(const char* json);

  bool connected_ = false;
  bool audio_done_pending_ = false;
  uint32_t last_attempt_ms_ = 0;
};

extern Net net;
