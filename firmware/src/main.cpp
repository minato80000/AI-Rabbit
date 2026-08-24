// ウサちゃんロボ CoreS3 ファームウェア
//
// PC 側が頭脳で、この機体は入出力の端末。
//   PC -> 音声(PCM) と 表情(state)
//   PC <- タッチ / 加速度センサ
//
// 音も声もこの機体で入出力する。ただし CoreS3 のマイクとスピーカーは I2S を
// 共有していて同時には開けないので、喋る間は耳を閉じる半二重になる。
// 切り替えは mic_in が持つ。docs/core-mic.md を参照。

#include <M5Unified.h>

#include "audio_out.h"
#include "config.h"
#include "face.h"
#include "mic_in.h"
#include "net.h"

namespace {

uint32_t last_touch_ms = 0;
uint32_t last_imu_ms = 0;

// ボタンの帯より上だけを PC へ送る。既定ではボタンは画面の外にあるので、
// 画面はすべて PC へ渡る
int touchAreaBottom() {
  return M5.Display.height() - (int)M5.getTouchButtonHeight();
}

// 画面より下の見えない帯の中央（BtnB）で、開発モードと製品モードを切り替える。
// CoreS3 に押しボタンは無く、タッチ面が画面の下まで続いているぶんが
// BtnA / BtnB / BtnC になっている
void pollModeButton() {
  if (!M5.BtnB.wasClicked()) return;
  const bool dev = face.toggleMode() == DisplayMode::Dev;
  Serial.printf("[main] %sモードへ切り替えました\n", dev ? "開発" : "製品");
}

// 画面に触られたら PC へ知らせる
void pollTouch() {
  auto t = M5.Touch.getDetail();
  if (!t.wasPressed()) return;
  if (t.y >= touchAreaBottom()) return;  // ボタンの帯。PC へは送らない
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
  // 構成するだけ。実際に開くのは mic_in が判断する（スピーカーと排他）
  cfg.internal_mic = true;
  cfg.internal_spk = true;
  M5.begin(cfg);

  // ボタンの範囲を明示しておく。0 なら画面の外（下の見えない帯）だけが
  // BtnA/BtnB/BtnC になる。値を与えると画面の下端まで巻き込む
  M5.setTouchButtonHeight(TOUCH_BUTTON_HEIGHT);

  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.printf("=== ウサちゃんロボ CoreS3 fw %s ===\n", FW_VERSION);

  face.begin();
  if (!audio_out.begin()) {
    Serial.println("[main] 音声の初期化に失敗しました");
  }
  mic_in.begin();
  net.begin();
}

void loop() {
  M5.update();

  net.update();
  audio_out.update();
  // 鳴っていないあいだだけマイクを開き、拾った音を PC へ流す。
  // audio_out.update() のあとに置くこと。鳴り終わった直後に耳を戻したい
  mic_in.update();

  // 再生中の音量から口の開き具合を決める。
  // PC 側で計算して送るより、実際に鳴らしているバッファを見るほうが同期が正確
  face.setMouth(audio_out.isPlaying() ? audio_out.level() : 0.0f);
  face.update();

  pollModeButton();
  pollTouch();
  pollImu();

  delay(2);
}
