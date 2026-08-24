// この機体のマイクで聞く。
//
// マイクとスピーカーは I2S1 と BCK/WS ピンを共有していて同時には開けないので、
// 半二重で切り替える:
//
//   PC から {"t":"mic","on":true}   -> 録って PC へバイナリで流す
//   スピーカーが鳴っているあいだ     -> マイクを閉じて I2S を明け渡す
//   鳴り終わったら                  -> マイクへ戻る
//
// 「鳴っているあいだ」は PC の指示を待たず自分で判断する。指示の行き違いで
// スピーカーとマイクが同時に開くと、どちらも壊れるため。
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "config.h"

class MicIn {
 public:
  bool begin();

  // PC からの {"t":"mic","on":..} を受ける
  void setWanted(bool on, uint32_t sample_rate);

  // 毎ループ呼ぶ。録れた分を PC へ送る
  void update();

  // いまマイクが開いているか（顔の表示などに使える）
  bool listening() const { return open_; }

 private:
  bool open();
  void close();

  int16_t* buf_[MIC_BUFFERS] = {nullptr};
  size_t slot_ = 0;       // 次に録音を投げるバッファ
  size_t queued_ = 0;     // 投げ済みで、まだ送っていない枚数（最大2）
  bool wanted_ = false;   // PC が聞きたがっているか
  bool open_ = false;     // 実際にマイクが開いているか
  uint32_t rate_ = MIC_SAMPLE_RATE;
  uint32_t opened_at_ = 0;
  uint32_t last_try_ms_ = 0;
};

extern MicIn mic_in;
