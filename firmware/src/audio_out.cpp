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
  // 既定のままだと DMA が浅く、Wi-Fi の到着ゆらぎで音が途切れる。
  // 深くすると滑らかになるが、閉じるときに捨てる量もその分だけ増える。
  // 深さと待ち時間は config.h で対にしてある（SPEAKER_DRAIN_MS）
  cfg.dma_buf_len = SPEAKER_DMA_BUF_LEN;
  cfg.dma_buf_count = SPEAKER_DMA_BUF_COUNT;
  cfg.task_priority = 3;  // 描画より優先させる
  M5.Speaker.config(cfg);
  M5.Speaker.begin();
  M5.Speaker.setVolume(200);

  // まだ何も鳴らしていないので、DMA の待ちは済んだことにしておく。
  // （unsigned の引き算なので millis() が小さいうちでも正しく回る）
  drained_at_ms_ = millis() - SPEAKER_DRAIN_MS;

  Serial.printf("[audio] リングバッファ %u サンプル (%u ms) / DMA の吐き切り %u ms\n",
                (unsigned)capacity_, (unsigned)RINGBUFFER_MS,
                (unsigned)SPEAKER_DRAIN_MS);
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
  M5.Speaker.stop(SPEAKER_CHANNEL);
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
  M5.Speaker.stop(SPEAKER_CHANNEL);
  reset();
  streaming_ = false;
  // 黙らせる指示なので、DMA に残っている分を守る意味はない。待ちを飛ばして
  // すぐマイクへ切り替えられるようにする（切り替えの end() が DMA ごと捨てる）
  drained_at_ms_ = millis() - SPEAKER_DRAIN_MS;
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

    // チャンネルは固定する。-1（自動割り当て）にすると連続するチャンクが
    // 別チャンネルに割り振られ、順番に鳴らず同時に重なって再生される。
    // 細かく途切れて聞こえる原因になる。
    if (!M5.Speaker.playRaw(&buf_[tail_], n, sample_rate_, false, 1,
                            SPEAKER_CHANNEL, false)) {
      break;  // このチャンネルのキューが一杯。次のループで送る
    }
    tail_ = (tail_ + n) % capacity_;
    have -= n;
    playing_ = true;
  }

  if (available() == 0 && !M5.Speaker.isPlaying(SPEAKER_CHANNEL)) {
    if (playing_) {
      // キューは空になったが、DMA にはまだ積んだ分が残っている。
      // finished() はここからの経過を見る
      drained_at_ms_ = millis();
    }
    playing_ = false;
    level_ = 0.0f;
    started_ = false;
  }
}

bool AudioOut::finished() const {
  if (streaming_ || playing_) return false;
  if (((head_ + capacity_ - tail_) % capacity_) != 0) return false;
  // キューが空でも DMA には残っている。ここで待たないと、マイクへ切り替える
  // ときの M5.Speaker.end() に語尾を持っていかれる
  return (millis() - drained_at_ms_) >= SPEAKER_DRAIN_MS;
}
