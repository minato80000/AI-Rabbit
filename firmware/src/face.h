// 画面に顔を描く。
//
// Step 4 で作り込む予定なので、いまは状態が分かる最小限の表示にとどめる。
// 目的は「PC から届いた state と emotion が正しく反映されるか」の確認。
#pragma once

#include <stdint.h>

enum class RobotState : uint8_t { Idle, Listening, Thinking, Speaking };
enum class Emotion : uint8_t { Neutral, Happy, Puzzled, Surprised };

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

 private:
  void draw();

  RobotState state_ = RobotState::Idle;
  Emotion emotion_ = Emotion::Neutral;
  bool connected_ = false;
  float mouth_ = 0.0f;

  RobotState drawn_state_ = RobotState::Speaking;  // 初回に必ず描き直させる
  Emotion drawn_emotion_ = Emotion::Surprised;
  bool drawn_connected_ = true;
  int drawn_mouth_ = -1;
  uint32_t last_blink_ms_ = 0;
  bool blinking_ = false;
};

extern Face face;

// 文字列から enum へ。PC 側の値と合わせること
RobotState parseState(const char* s);
Emotion parseEmotion(const char* s);
