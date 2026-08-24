#include "mic_in.h"

#include <M5Unified.h>
#include <stdlib.h>  // malloc

#include "audio_out.h"
#include "net.h"

MicIn mic_in;

bool MicIn::begin() {
  // 内蔵 RAM に置く。3枚でも 3KB しかなく、PSRAM 越しに読み書きするより速い
  for (size_t i = 0; i < MIC_BUFFERS; ++i) {
    buf_[i] = (int16_t*)malloc(MIC_FRAME_SAMPLES * sizeof(int16_t));
    if (buf_[i] == nullptr) {
      Serial.println("[mic] 録音バッファを確保できません");
      return false;
    }
  }
  Serial.printf("[mic] マイク入力 (%u Hz, %u サンプル/フレーム)\n",
                (unsigned)MIC_SAMPLE_RATE, (unsigned)MIC_FRAME_SAMPLES);
  return true;
}

void MicIn::setWanted(bool on, uint32_t sample_rate) {
  if (sample_rate != 0 && sample_rate != rate_) {
    rate_ = sample_rate;
    if (open_) close();  // 次の update() で新しいレートで開き直す
  }
  if (on == wanted_) return;
  wanted_ = on;
  Serial.printf("[mic] PC の指示: %s\n", on ? "開く" : "閉じる");
}

bool MicIn::open() {
  if (open_) return true;

  if (!M5.Mic.isEnabled()) {
    // main.cpp の M5.config() で internal_mic を立て忘れている。
    // スピーカーを止める前に気づくこと。止めたまま戻ると声まで出なくなる
    Serial.println("[mic] マイクが構成されていません (cfg.internal_mic)");
    return false;
  }

  // I2S を明け渡してもらう。同時には開けない
  M5.Speaker.end();

  auto cfg = M5.Mic.config();
  cfg.sample_rate = rate_;
  cfg.magnification = MIC_MAGNIFICATION;
  M5.Mic.config(cfg);

  if (!M5.Mic.begin()) {
    Serial.println("[mic] マイクを開けませんでした");
    M5.Speaker.begin();  // 少なくとも喋れる状態には戻しておく
    return false;
  }

  open_ = true;
  slot_ = 0;
  queued_ = 0;
  opened_at_ = millis();
  return true;
}

void MicIn::close() {
  if (!open_) return;
  M5.Mic.end();
  open_ = false;
  queued_ = 0;
  // スピーカーを戻す。config と音量は保持されているので begin() だけでよい
  M5.Speaker.begin();
}

void MicIn::update() {
  // 鳴っているあいだは I2S を譲る。PC の指示より、いま鳴っているかを優先する
  const bool should = wanted_ && net.connected() && audio_out.finished();

  if (!should) {
    close();
    return;
  }
  if (!open_) {
    // 開けなかったときに毎ループ叩かない
    if (millis() - last_try_ms_ < MIC_RETRY_MS) return;
    last_try_ms_ = millis();
    if (!open()) return;
  }

  // M5Unified は録音要求を2枚まで先行して受ける。record() が戻った時点で
  // 「2つ前に投げた1枚」は録り終わっているが、2枚で回すとその1枚を
  // 次の record() が上書きしてしまう。3枚で回して送る余地を作る。
  const bool warming = (millis() - opened_at_) < MIC_WARMUP_MS;
  for (int i = 0; i < 3; ++i) {
    if (M5.Mic.isRecording() >= 2) break;  // 空きが無い。待つと loop が止まる
    if (!M5.Mic.record(buf_[slot_], MIC_FRAME_SAMPLES, rate_)) {
      Serial.println("[mic] 録音要求が通りませんでした");
      close();
      return;
    }
    if (queued_ >= 2) {
      // 開いた直後は値が安定しないので、その間のフレームは捨てる
      if (!warming) {
        net.sendMicFrame(buf_[(slot_ + 1) % MIC_BUFFERS], MIC_FRAME_SAMPLES);
      }
    } else {
      ++queued_;
    }
    slot_ = (slot_ + 1) % MIC_BUFFERS;
  }
}
