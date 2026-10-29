// 画面に顔を描く。
//
// スプライト（M5Canvas）にいったん描いてから画面へ送る。画面へ直接描くと
// 「消してから描き直すまで」が見えてちらつくため。
//
// 送るのは変わった場所だけ。全画面は 320x240x2 = 150KB あり、SPI 40MHz でも
// 30ms 以上かかる。PSRAM に置いたスプライトは DMA が効かない（LovyanGFX が
// PSRAM のバッファでは DMA を切る）ので実際はさらに延びる。
//
// これは見た目の問題では済まない。**この機体はマイクの録音バッファを
// loop() で積み直しており、その猶予は 512 サンプル x 2 枚 = 64ms しかない。**
// 口が動くたびに全画面を送ると、マイクの音が欠ける。
#pragma once

#include <M5Unified.h>
#include <stdint.h>

enum class RobotState : uint8_t { Idle, Listening, Thinking, Speaking };
enum class Emotion : uint8_t { Neutral, Happy, Puzzled, Surprised, Sleepy };

// 画面の見せ方。起動時は Dev。
//   Dev     : state のラベルや接続状態を顔に重ねる。開発中に見たい情報
//   Product : 顔だけ。人に見せる状態。繋がっていないときの一文だけは残る
// 切り替えは画面下中央のタッチ（BtnB）。main.cpp を参照
enum class DisplayMode : uint8_t { Dev, Product };

class Face {
 public:
  void begin();

  // PC から届いた state / emotion を反映する
  void set(RobotState state, Emotion emotion);

  // 口の開き具合（0.0〜1.0）。再生中の音量から決まる
  void setMouth(float level);

  // 接続状態。切れているときは分かるようにしておく
  void setConnected(bool connected);

  void update();

  RobotState state() const { return state_; }

  // 開発モード / 製品モード
  void setMode(DisplayMode mode);
  DisplayMode mode() const { return mode_; }
  DisplayMode toggleMode();

  // スプライトを確保できたか。できなければ画面へ直接描いている（ちらつく）
  bool buffered() const { return use_sprite_; }

 private:
  // 描画本体。描く先を選ばないので、スプライトにも画面にも同じ絵を描ける
  void render(LovyanGFX& g);

  // スプライトの指定範囲だけを画面へ送る
  void flush(int x, int y, int w, int h);

  // 描いて送る。full=true なら全画面、false なら変わった部位だけ
  void present(bool full, bool mouth, bool eyes);

  RobotState state_ = RobotState::Idle;
  Emotion emotion_ = Emotion::Neutral;
  bool connected_ = false;
  float mouth_ = 0.0f;
  DisplayMode mode_ = DisplayMode::Dev;

  RobotState drawn_state_ = RobotState::Speaking;  // 初回に必ず描き直させる
  Emotion drawn_emotion_ = Emotion::Surprised;
  bool drawn_connected_ = true;
  DisplayMode drawn_mode_ = DisplayMode::Product;
  int drawn_mouth_ = -1;
  bool drawn_blink_ = false;
  uint32_t last_blink_ms_ = 0;
  bool blinking_ = false;

  M5Canvas canvas_;
  bool use_sprite_ = false;
  uint32_t last_push_ms_ = 0;
  uint32_t slow_frames_ = 0;
};

extern Face face;

// 文字列から enum へ。PC 側の値と合わせること
RobotState parseState(const char* s);
Emotion parseEmotion(const char* s);
