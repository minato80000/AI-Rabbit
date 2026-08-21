// ウサちゃんロボ CoreS3 ファームウェア
//
// PC 側が頭脳で、この機体は入出力の端末。
//   PC -> 音声(PCM) と 表情(state)
//   PC <- タッチ / 加速度センサ
//
// 音声入力は PC 側のマイクを使うため、この機体では扱わない。
// CoreS3 はマイクとスピーカーが I2S を共有していて同時使用に制約があるので、
// 入力を PC に逃がしたこの構成なら、その問題を避けられる。

#include <M5Unified.h>

#include "audio_out.h"
#include "config.h"
#include "face.h"
#include "net.h"

namespace {

uint32_t last_touch_ms = 0;
uint32_t last_imu_ms = 0;

// 画面に触られたら PC へ知らせる
void pollTouch() {
  auto t = M5.Touch.getDetail();
  if (!t.wasPressed()) return;
  uint32_t now = millis();
  if (now - last_touch_ms < TOUCH_MIN_INTERVAL_MS) return;
  last_touch_ms = now;
  net.sendTouch(t.x, t.y);
  Serial.printf("[touch] %d,%d\n", t.x, t.y);
}

// 持ち上げ・振りを見る
void pollImu() {
  if (!M5.Imu.update()) return;
  uint32_t now = millis();
  if (now - last_imu_ms < IMU_MIN_INTERVAL_MS) return;

  auto d = M5.Imu.getImuData();
  float g = sqrtf(d.accel.x * d.accel.x + d.accel.y * d.accel.y +
                  d.accel.z * d.accel.z);

  const char* event = nullptr;
  if (g > IMU_SHAKE_G) {
    event = "shake";
  } else if (g < IMU_LIFT_G && g > 0.2f) {
    // 落下方向の加速度が抜けている = 持ち上げられた
    event = "lift";
  }
  if (event == nullptr) return;

  last_imu_ms = now;
  net.sendImu(event);
  Serial.printf("[imu] %s (%.2fg)\n", event, g);
}

}  // namespace

void setup() {
  auto cfg = M5.config();
  cfg.internal_imu = true;
  cfg.internal_mic = false;  // マイクは使わない。スピーカーと I2S を取り合うため
  cfg.internal_spk = true;
  M5.begin(cfg);

  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.printf("=== ウサちゃんロボ CoreS3 fw %s ===\n", FW_VERSION);

  face.begin();
  if (!audio_out.begin()) {
    Serial.println("[main] 音声の初期化に失敗しました");
  }
  net.begin();
}

void loop() {
  M5.update();

  net.update();
  audio_out.update();

  // 再生中の音量から口の開き具合を決める。
  // PC 側で計算して送るより、実際に鳴らしているバッファを見るほうが同期が正確
  face.setMouth(audio_out.isPlaying() ? audio_out.level() : 0.0f);
  face.update();

  pollTouch();
  pollImu();

  delay(2);
}
