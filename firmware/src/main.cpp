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
