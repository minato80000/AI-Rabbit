#include "face.h"

#include <string.h>

#include "config.h"

Face face;

// ---- 顔スタジオで生成 ----
namespace {
constexpr int kEyeY = 100;
constexpr int kMouthY = 116;

// 部分転送の範囲。すべての分岐（口は開き最大）の外接矩形から算出した。
// 描画を変えたら、顔スタジオで出し直すこと。
constexpr int kMouthBoxW = 138;
constexpr int kMouthBoxH = 360;
constexpr int kEyeBoxW = 214;
constexpr int kEyeBoxH = 74;

uint16_t backgroundFor(LovyanGFX& g, Emotion e) {
  switch (e) {
    case Emotion::Happy:     return g.color565(255, 255, 197);
    case Emotion::Puzzled:   return g.color565(255, 255, 197);
    case Emotion::Surprised: return g.color565(255, 255, 197);
    case Emotion::Sleepy:    return g.color565(255, 255, 197);
    default:                 return g.color565(255, 255, 197);
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
  if (strcmp(s, "sleepy") == 0) return Emotion::Sleepy;
  return Emotion::Neutral;
}

void Face::begin() {
  M5.Display.setRotation(1);

  // PSRAM に置く。内蔵 RAM は WiFi と音声に残しておきたい。
  // PSRAM のスプライトは DMA が効かないぶん送るのが遅いが、遅さが効くのは
  // 全画面を送るときだけ。その全画面は state / emotion が変わったときに起き、
  // そのときマイクは PC の指示で閉じているので、ちょうど噛み合っている。
  canvas_.setPsram(true);
  canvas_.setColorDepth(16);
  use_sprite_ =
      canvas_.createSprite(M5.Display.width(), M5.Display.height()) != nullptr;

  if (use_sprite_) {
    Serial.printf("[face] スプライト %dx%d (%u KB, PSRAM)\n",
                  M5.Display.width(), M5.Display.height(),
                  (unsigned)(M5.Display.width() * M5.Display.height() * 2 / 1024));
  } else {
    Serial.println("[face] スプライトを確保できません。画面へ直接描きます（ちらつきます）");
  }

  present(true, true, true);
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

void Face::setMode(DisplayMode mode) {
  mode_ = mode;
}

DisplayMode Face::toggleMode() {
  mode_ = (mode_ == DisplayMode::Dev) ? DisplayMode::Product : DisplayMode::Dev;
  return mode_;
}

void Face::update() {
  const uint32_t now = millis();

  // まばたき。待機中だけ
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

  const int mouth_step = (int)(mouth_ * 5.0f);
  const bool big = state_ != drawn_state_ || emotion_ != drawn_emotion_ ||
                   connected_ != drawn_connected_ || mode_ != drawn_mode_;
  const bool mouth_changed = mouth_step != drawn_mouth_;
  const bool blink_changed = blinking_ != drawn_blink_;
  if (!big && !mouth_changed && !blink_changed) return;

  // 口とまばたきは送りすぎを抑える。state / emotion の変化は待たせない
  // （待たせると反応が鈍く見える）
  if (!big && (now - last_push_ms_) < FACE_MIN_FRAME_MS) return;

  drawn_state_ = state_;
  drawn_emotion_ = emotion_;
  drawn_connected_ = connected_;
  drawn_mode_ = mode_;
  drawn_mouth_ = mouth_step;
  drawn_blink_ = blinking_;

  present(big, mouth_changed, blink_changed);
}

void Face::present(bool full, bool mouth, bool eyes) {
  const uint32_t t0 = millis();
  const int cx = M5.Display.width() / 2;

  if (!use_sprite_) {
    // 確保できなかったときの保険。ちらつくが、何も映らないよりはよい
    render(M5.Display);
  } else {
    render(canvas_);
    if (full) {
      flush(0, 0, M5.Display.width(), M5.Display.height());
    } else {
      if (mouth) {
        flush(cx - kMouthBoxW / 2, kMouthY - kMouthBoxH / 2, kMouthBoxW, kMouthBoxH);
      }
      if (eyes) {
        flush(cx - kEyeBoxW / 2, kEyeY - kEyeBoxH / 2, kEyeBoxW, kEyeBoxH);
      }
    }
  }

  last_push_ms_ = millis();

  // 描画が長引くとマイクの録音バッファを積み直せず、音が欠ける。
  // 気づけるように出しておく（毎回出すとシリアルが埋まるので間引く）
  const uint32_t took = last_push_ms_ - t0;
  if (took >= FACE_SLOW_FRAME_MS) {
    ++slow_frames_;
    if ((slow_frames_ & 31) == 1) {
      Serial.printf("[face] 描画に %ums かかりました（累計 %u 回）。"
                    "マイクの猶予は 64ms です\n",
                    (unsigned)took, (unsigned)slow_frames_);
    }
  }
}

void Face::flush(int x, int y, int w, int h) {
  // クリップを掛けてから送ると、LovyanGFX は範囲内の画素だけを転送する
  // （LGFXBase::pushImage が clip で切ってから writeImage を呼ぶ）。
  // 全画面 150KB を毎回送らずに済むのはこのため。
  M5.Display.setClipRect(x, y, w, h);
  canvas_.pushSprite(&M5.Display, 0, 0);
  M5.Display.clearClipRect();
}

void Face::render(LovyanGFX& g) {
  const int cx = g.width() / 2;

  g.fillScreen(backgroundFor(g, emotion_));

  // ---- 常時 ----
  g.fillEllipse(cx - 129, 150, 23, 11, TFT_BLACK);
  g.fillEllipse(cx + 129, 150, 23, 11, TFT_BLACK);
  g.fillEllipse(cx - 129, 150, 20, 9, g.color565(240, 150, 170));
  g.fillEllipse(cx + 129, 150, 20, 9, g.color565(240, 150, 170));

  // ---- 目 ----
  if (blinking_) {
    g.fillRoundRect(cx - 102, 93, 44, 6, 3, TFT_BLACK);
    g.fillRoundRect(cx + 58, 93, 44, 6, 3, TFT_BLACK);
  } else if (state_ == RobotState::Thinking) {
    g.fillCircle(cx - 80, 90, 22, TFT_BLACK);
    g.fillCircle(cx + 80, 90, 22, TFT_BLACK);
    g.fillCircle(cx - 90, 80, 6, TFT_WHITE);
    g.fillCircle(cx + 70, 80, 6, TFT_WHITE);
  } else if (emotion_ == Emotion::Surprised) {
    g.fillCircle(cx - 80, 90, 27, TFT_BLACK);
    g.fillCircle(cx + 80, 90, 27, TFT_BLACK);
    g.fillCircle(cx - 90, 80, 10, TFT_WHITE);
    g.fillCircle(cx + 70, 80, 10, TFT_WHITE);
  } else {
    g.fillCircle(cx - 80, 90, 22, TFT_BLACK);
    g.fillCircle(cx + 80, 90, 22, TFT_BLACK);
    g.fillCircle(cx - 90, 80, 6, TFT_WHITE);
    g.fillCircle(cx + 70, 80, 6, TFT_WHITE);
  }

  // ---- 口 ----
  if (state_ == RobotState::Speaking) {
    int h = 0 + (int)(mouth_ * 93.0f);   // 縦半径
    int h2 = 0 + (int)(mouth_ * 90.0f);   // 縦半径
    g.fillEllipse(cx, 130, 38, h, TFT_BLACK);
    g.fillEllipse(cx, 130, 35, h2, g.color565(255, 178, 174));
    g.fillEllipse(cx - 26, 113, 32, 23, TFT_BLACK);
    g.fillEllipse(cx + 26, 113, 32, 23, TFT_BLACK);
    g.fillEllipse(cx - 26, 113, 29, 20, g.color565(255, 255, 197));
    g.fillEllipse(cx + 26, 113, 29, 20, g.color565(255, 255, 197));
    g.fillRect(cx - 57, -64, 115, 177, g.color565(255, 255, 197));
    g.fillRect(cx - 69, 109, 22, 23, g.color565(255, 255, 197));
    g.fillRect(cx + 47, 109, 22, 23, g.color565(255, 255, 197));
    g.fillEllipse(cx, 110, 6, 4, TFT_BLACK);
    g.fillEllipse(cx, 110, 4, 2, g.color565(240, 150, 170));
  } else if (emotion_ == Emotion::Happy) {
    g.fillCircle(cx, 125, 47, TFT_BLACK);
    g.fillCircle(cx, 125, 44, g.color565(255, 178, 174));
    g.fillEllipse(cx - 26, 113, 32, 23, TFT_BLACK);
    g.fillEllipse(cx + 26, 113, 32, 23, TFT_BLACK);
    g.fillEllipse(cx - 26, 113, 29, 20, g.color565(255, 255, 197));
    g.fillEllipse(cx + 26, 113, 29, 20, g.color565(255, 255, 197));
    g.fillRect(cx - 57, 61, 115, 58, g.color565(255, 255, 197));
    g.fillRect(cx - 69, 109, 22, 23, g.color565(255, 255, 197));
    g.fillRect(cx + 47, 109, 22, 23, g.color565(255, 255, 197));
    g.fillEllipse(cx, 110, 6, 4, TFT_BLACK);
    g.fillEllipse(cx, 110, 4, 2, g.color565(240, 150, 170));
  } else if (emotion_ == Emotion::Puzzled) {
    g.fillCircle(cx + 2, 90, 47, TFT_BLACK);
    g.fillCircle(cx + 2, 90, 44, g.color565(255, 178, 174));
    g.fillEllipse(cx - 26, 113, 32, 23, TFT_BLACK);
    g.fillEllipse(cx + 26, 113, 32, 23, TFT_BLACK);
    g.fillEllipse(cx - 26, 113, 29, 20, g.color565(255, 255, 197));
    g.fillEllipse(cx + 26, 113, 29, 20, g.color565(255, 255, 197));
    g.fillRect(cx - 56, 40, 114, 73, g.color565(255, 255, 197));
    g.fillRect(cx - 63, 107, 22, 23, g.color565(255, 255, 197));
    g.fillRect(cx + 41, 107, 22, 23, g.color565(255, 255, 197));
    g.fillEllipse(cx, 110, 6, 4, TFT_BLACK);
    g.fillEllipse(cx, 110, 4, 2, g.color565(240, 150, 170));
  } else {
    g.fillCircle(cx, 125, 47, TFT_BLACK);
    g.fillCircle(cx, 125, 44, g.color565(255, 178, 174));
    g.fillEllipse(cx - 26, 113, 32, 23, TFT_BLACK);
    g.fillEllipse(cx + 26, 113, 32, 23, TFT_BLACK);
    g.fillEllipse(cx - 26, 113, 29, 20, g.color565(255, 255, 197));
    g.fillEllipse(cx + 26, 113, 29, 20, g.color565(255, 255, 197));
    g.fillRect(cx - 57, 61, 115, 58, g.color565(255, 255, 197));
    g.fillRect(cx - 69, 109, 22, 23, g.color565(255, 255, 197));
    g.fillRect(cx + 47, 109, 22, 23, g.color565(255, 255, 197));
    g.fillEllipse(cx, 110, 6, 4, TFT_BLACK);
    g.fillEllipse(cx, 110, 4, 2, g.color565(240, 150, 170));
  }

  // ---- ここから下は開発モードだけ ----
  if (mode_ != DisplayMode::Dev) {
    // 製品モードでは state のラベルを出さない。ただし繋がっていないことが
    // まったく分からないと困るので、それだけは文字で出す
    if (!connected_) {
      g.setTextSize(1);
      g.setTextDatum(textdatum_t::top_left);
      g.setTextColor(g.color565(230, 140, 90));
      g.drawString("U-cyber network not connected", 6, 6);
    }
    return;
  }

  g.setTextSize(1);
  g.setTextDatum(textdatum_t::top_left);
  g.setTextColor(g.color565(120, 130, 140));
  const char* label = "idle";
  switch (state_) {
    case RobotState::Listening: label = "listening"; break;
    case RobotState::Thinking:  label = "thinking";  break;
    case RobotState::Speaking:  label = "speaking";  break;
    default: break;
  }
  g.drawString(label, 6, 6);
  if (!connected_) {
    g.setTextColor(g.color565(230, 140, 90));
    g.drawString("PC not connected", 6, 20);
  }

  g.setTextDatum(textdatum_t::bottom_center);
  g.setTextColor(g.color565(96, 106, 116));
  g.drawString("DEV - tap below the screen", cx, g.height() - 3);
  g.setTextDatum(textdatum_t::top_left);
}
