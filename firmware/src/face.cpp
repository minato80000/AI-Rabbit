#include "face.h"

#include <M5Unified.h>
#include <string.h>

Face face;

namespace {
constexpr int kEyeY = 100;
constexpr int kEyeDx = 62;
constexpr int kEyeR = 22;
constexpr int kMouthY = 170;

uint16_t backgroundFor(Emotion e) {
  switch (e) {
    case Emotion::Happy:     return M5.Display.color565(20, 40, 28);
    case Emotion::Puzzled:   return M5.Display.color565(38, 32, 20);
    case Emotion::Surprised: return M5.Display.color565(38, 24, 24);
    default:                 return M5.Display.color565(16, 20, 26);
  }
}
}  // namespace

RobotState parseState(const char* s) {
  if (s == nullptr) return RobotState::Idle;
  if (strcmp(s, "listening") == 0) return RobotState::Listening;
  if (strcmp(s, "thinking") == 0) return RobotState::Thinking;
  if (strcmp(s, "speaking") == 0) return RobotState::Speaking;
  return RobotState::Idle;
}

Emotion parseEmotion(const char* s) {
  if (s == nullptr) return Emotion::Neutral;
  if (strcmp(s, "happy") == 0) return Emotion::Happy;
  if (strcmp(s, "puzzled") == 0) return Emotion::Puzzled;
  if (strcmp(s, "surprised") == 0) return Emotion::Surprised;
  return Emotion::Neutral;
}

void Face::begin() {
  M5.Display.setRotation(1);
  M5.Display.setTextDatum(textdatum_t::top_left);
  draw();
}

void Face::set(RobotState state, Emotion emotion) {
  state_ = state;
  emotion_ = emotion;
}

void Face::setMouth(float level) {
  // そのまま使うと動きが小さいので持ち上げる
  float v = level * 6.0f;
  mouth_ = v > 1.0f ? 1.0f : v;
}

void Face::setConnected(bool connected) {
  connected_ = connected;
}

void Face::update() {
  // まばたき。待機中だけ
  uint32_t now = millis();
  if (state_ == RobotState::Idle || state_ == RobotState::Listening) {
    if (!blinking_ && now - last_blink_ms_ > 3800) {
      blinking_ = true;
      last_blink_ms_ = now;
    } else if (blinking_ && now - last_blink_ms_ > 140) {
      blinking_ = false;
      last_blink_ms_ = now;
    }
  } else if (blinking_) {
    blinking_ = false;
  }

  int mouth_step = (int)(mouth_ * 5.0f);
  bool changed = state_ != drawn_state_ || emotion_ != drawn_emotion_ ||
                 connected_ != drawn_connected_ || mouth_step != drawn_mouth_;
  static bool drawn_blink = false;
  if (blinking_ != drawn_blink) {
    changed = true;
    drawn_blink = blinking_;
  }
  if (!changed) return;

  drawn_state_ = state_;
  drawn_emotion_ = emotion_;
  drawn_connected_ = connected_;
  drawn_mouth_ = mouth_step;
  draw();
}

void Face::draw() {
  auto& d = M5.Display;
  const int cx = d.width() / 2;

  d.fillScreen(backgroundFor(emotion_));

  // ---- 目 ----
  const uint16_t eye = TFT_WHITE;
  if (blinking_) {
    d.fillRoundRect(cx - kEyeDx - kEyeR, kEyeY - 3, kEyeR * 2, 6, 3, eye);
    d.fillRoundRect(cx + kEyeDx - kEyeR, kEyeY - 3, kEyeR * 2, 6, 3, eye);
  } else if (state_ == RobotState::Thinking) {
    // 考えているときは視線を上へ
    d.fillCircle(cx - kEyeDx, kEyeY - 8, kEyeR, eye);
    d.fillCircle(cx + kEyeDx, kEyeY - 8, kEyeR, eye);
    d.fillCircle(cx - kEyeDx, kEyeY - 14, 8, TFT_BLACK);
    d.fillCircle(cx + kEyeDx, kEyeY - 14, 8, TFT_BLACK);
  } else if (emotion_ == Emotion::Surprised) {
    d.fillCircle(cx - kEyeDx, kEyeY, kEyeR + 5, eye);
    d.fillCircle(cx + kEyeDx, kEyeY, kEyeR + 5, eye);
    d.fillCircle(cx - kEyeDx, kEyeY, 9, TFT_BLACK);
    d.fillCircle(cx + kEyeDx, kEyeY, 9, TFT_BLACK);
  } else {
    d.fillCircle(cx - kEyeDx, kEyeY, kEyeR, eye);
    d.fillCircle(cx + kEyeDx, kEyeY, kEyeR, eye);
    d.fillCircle(cx - kEyeDx, kEyeY + 4, 9, TFT_BLACK);
    d.fillCircle(cx + kEyeDx, kEyeY + 4, 9, TFT_BLACK);
  }

  // ---- 口 ----
  const uint16_t mouth = M5.Display.color565(240, 150, 170);
  if (state_ == RobotState::Speaking) {
    int h = 6 + (int)(mouth_ * 34.0f);
    d.fillRoundRect(cx - 26, kMouthY - h / 2, 52, h, 8, mouth);
  } else if (emotion_ == Emotion::Happy) {
    d.fillRoundRect(cx - 30, kMouthY - 4, 60, 10, 5, mouth);
  } else if (emotion_ == Emotion::Puzzled) {
    d.fillRoundRect(cx - 18, kMouthY, 36, 7, 3, mouth);
  } else {
    d.fillRoundRect(cx - 22, kMouthY - 3, 44, 7, 3, mouth);
  }

  // ---- 状態の表示（開発中の確認用。Step 4 で消す） ----
  d.setTextColor(M5.Display.color565(120, 130, 140));
  d.setTextSize(1);
  const char* label = "idle";
  switch (state_) {
    case RobotState::Listening: label = "listening"; break;
    case RobotState::Thinking:  label = "thinking";  break;
    case RobotState::Speaking:  label = "speaking";  break;
    default: break;
  }
  d.drawString(label, 6, 6);
  if (!connected_) {
    d.setTextColor(M5.Display.color565(230, 140, 90));
    d.drawString("PC not connected", 6, 20);
  }
}
