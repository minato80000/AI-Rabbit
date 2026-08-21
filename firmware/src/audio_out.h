// 受信した PCM を溜めてスピーカーへ流す。
//
// WebSocket は不定期に届くので、そのまま鳴らすと途切れる。
// いったんリングバッファに積み、一定量たまってから再生を始める。
#pragma once

#include <stddef.h>
#include <stdint.h>

class AudioOut {
 public:
  bool begin();

  // 新しい発話の開始。バッファを空にして溜め直す
  void beginStream(uint32_t sample_rate);

  // PCM チャンクを積む。入りきらなければ古い方を捨てる
  void push(const int16_t* data, size_t samples);

  // これ以上は届かない。溜まっている分は最後まで鳴らす
  void endStream();

  // barge-in。溜めた分も再生中の音も捨てて即座に止める
  void flush();

  // 毎ループ呼ぶ。溜まった分をスピーカーへ渡す
  void update();

  // 鳴らし終わったか（endStream 済みで、バッファも空）
  bool finished() const;

  // 再生中か（口パクに使う）
  bool isPlaying() const { return playing_; }

  // 直近チャンクの音量（0.0〜1.0）。口の開き具合に使う
  float level() const { return level_; }

 private:
  size_t available() const;
  void reset();

  int16_t* buf_ = nullptr;
  size_t capacity_ = 0;   // サンプル数
  size_t head_ = 0;       // 書き込み位置
  size_t tail_ = 0;       // 読み出し位置
  size_t prebuffer_ = 0;  // 再生開始に必要なサンプル数

  uint32_t sample_rate_ = 24000;
  bool streaming_ = false;  // PC がまだ送ってくる
  bool started_ = false;    // プリバッファを超えて再生を開始した
  bool playing_ = false;
  float level_ = 0.0f;
  uint32_t dropped_ = 0;
};

extern AudioOut audio_out;
