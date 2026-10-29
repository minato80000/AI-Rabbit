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
#include <esp_heap_caps.h>

#include "audio_out.h"
#include "config.h"
#include "face.h"
#include "mic_in.h"
#include "net.h"

// 画面より下の見えない帯の中央（BtnB）で、開発モードと製品モードを切り替える。
// CoreS3 に押しボタンは無く、タッチ面が画面の下まで続いているぶんが
// BtnA / BtnB / BtnC になっている
void pollModeButton()
{
  // wasClicked() ではなく wasReleased() を見る。**押している時間で取りこぼす**
  // ため。M5Unified の Button_Class は 500ms（_msecHold）押されると _press を
  // 2（hold）へ上げ、そこから離しても state_clicked にはならない。
  // 効かないときほど長く押したくなるので、離した時点で切り替える
  if (!M5.BtnB.wasReleased())
    return;
  const bool dev = face.toggleMode() == DisplayMode::Dev;
  Serial.printf("[main] %sモードへ切り替えました\n", dev ? "開発" : "製品");
}

void setup()
{
  auto cfg = M5.config();
  cfg.output_power = false;
  cfg.internal_mic = true;
  cfg.internal_spk = true;
  M5.begin(cfg);

  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.printf("=== ウサちゃんロボ CoreS3 fw %s ===\n", FW_VERSION);

  // PSRAM が見えていないと、顔のスプライト 150KB と音声リングバッファ 48KB が
  // 内蔵 RAM (320KB) から取られる。WiFi に回る分が減るので、この状態で音や
  // 通信を評価すると判断を誤る。
  //
  // **書き込み直後は必ずこうなる。** esptool は RTS でリセットするだけで電源を
  // 落とさず、ESP32-S3 の OPI PSRAM は電源が切れないリセットだとブートローダの
  // ID 読みに応答しないことがある（コールドブートなら出ない）
  // **psramFound() は使わない。** 初期化に失敗していても true を返すことが
  // あり、実測でそうなった（face は PSRAM、audio は内蔵RAM と、同じ起動で
  // 食い違って出た）。実際に確保できる領域があるかを見る
  if (heap_caps_get_free_size(MALLOC_CAP_SPIRAM) == 0)
  {
    Serial.println("[main] PSRAM が見えていません。電源を入れ直してください");
    Serial.println("[main] 書き込み直後のリセットではよく起きます。"
                   "この状態の音や通信は当てになりません");
  }

  face.begin();
  if (!audio_out.begin())
  {
    Serial.println("[main] 音声の初期化に失敗しました");
  }
  mic_in.begin();
  net.begin();
}

void loop()
{
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

  delay(2);
}
