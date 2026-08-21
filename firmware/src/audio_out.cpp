#include "audio_out.h"

#include <M5Unified.h>
#include <esp_heap_caps.h>
#include <math.h>

#include "config.h"

AudioOut audio_out;

bool AudioOut::begin() {
  capacity_ = (size_t)(AUDIO_SAMPLE_RATE * RINGBUFFER_MS / 1000);
  prebuffer_ = (size_t)(AUDIO_SAMPLE_RATE * PREBUFFER_MS / 1000);

  // 内蔵 RAM は画面や WiFi に使いたいので、まず PSRAM を試す
  buf_ = (int16_t*)heap_caps_malloc(capacity_ * sizeof(int16_t), MALLOC_CAP_SPIRAM);
  if (buf_ == nullptr) {
    buf_ = (int16_t*)malloc(capacity_ * sizeof(int16_t));
  }
  if (buf_ == nullptr) {
    Serial.println("[audio] リングバッファを確保できません");
    return false;
  }

  auto cfg = M5.Speaker.config();
  cfg.sample_rate = AUDIO_SAMPLE_RATE;
  cfg.stereo = false;
  M5.Speaker.config(cfg);
  M5.Speaker.begin();
  M5.Speaker.setVolume(200);

  Serial.printf("[audio] リングバッファ %u サンプル (%u ms)\n",
                (unsigned)capacity_, (unsigned)RINGBUFFER_MS);
  return true;
}

size_t AudioOut::available() const {
  return (head_ + capacity_ - tail_) % capacity_;
}

void AudioOut::reset() {
  head_ = 0;
  tail_ = 0;
  started_ = false;
  playing_ = false;
  level_ = 0.0f;
}

void AudioOut::beginStream(uint32_t sample_rate) {
  M5.Speaker.stop();
  reset();
  streaming_ = true;
  dropped_ = 0;
  if (sample_rate != 0) {
    sample_rate_ = sample_rate;
  }
}

void AudioOut::push(const int16_t* data, size_t samples) {
  if (buf_ == nullptr || samples == 0) return;

  // 音量を測っておく。口パクに使う
  float sum = 0.0f;
  for (size_t i = 0; i < samples; ++i) {
    float v = data[i] / 32768.0f;
    sum += v * v;
  }
  level_ = sqrtf(sum / samples);

  for (size_t i = 0; i < samples; ++i) {
    size_t next = (head_ + 1) % capacity_;
    if (next == tail_) {
      // 溢れた。古い方を捨てて追いつく（遅延を溜めない）
      tail_ = (tail_ + 1) % capacity_;
      ++dropped_;
    }
    buf_[head_] = data[i];
    head_ = next;
  }

  if (dropped_ > 0 && (dropped_ % 4800) < samples) {
    Serial.printf("[audio] バッファ溢れ %u サンプル\n", (unsigned)dropped_);
  }
}

void AudioOut::endStream() {
  streaming_ = false;
}

void AudioOut::flush() {
  M5.Speaker.stop();
  reset();
  streaming_ = false;
}

void AudioOut::update() {
  if (buf_ == nullptr) return;

  size_t have = available();

  // 溜まるまで待つ。ただし PC が送り終えていれば残りを鳴らしきる
  if (!started_) {
    if (have < prebuffer_ && streaming_) return;
    if (have == 0) return;
    started_ = true;
  }

  while (have > 0) {
    size_t n = have < SPEAKER_CHUNK_SAMPLES ? have : SPEAKER_CHUNK_SAMPLES;
    // リングの折り返しをまたがないように切る
    if (tail_ + n > capacity_) n = capacity_ - tail_;

    if (!M5.Speaker.playRaw(&buf_[tail_], n, sample_rate_, false, 1, -1, false)) {
      break;  // スピーカー側のキューが一杯。次のループで送る
    }
    tail_ = (tail_ + n) % capacity_;
    have -= n;
    playing_ = true;
  }

  if (available() == 0 && !M5.Speaker.isPlaying()) {
    playing_ = false;
    level_ = 0.0f;
    started_ = false;
  }
}

bool AudioOut::finished() const {
  return !streaming_ && !playing_ && ((head_ + capacity_ - tail_) % capacity_) == 0;
}
