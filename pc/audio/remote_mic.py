"""CoreS3 のマイクを入力として読む（既定の入力元）。

CoreS3 のマイクとスピーカーは I2S1 と BCK/WS ピンを共有していて同時には
開けない。つまりロボットは**喋っている間は耳が塞がる**（半二重）。
その代わり自分の声を拾いようがないので、音響エコーは起きない。

PC のマイクで聞きたいときは config.yaml の `audio.input` を `local` に
（または --pc-mic）。ロボットの聞こえが怪しいときの切り分けに使う。

Mic と同じ形（sample_rate / frame_samples / queue / paused / start / stop /
frames）を持たせてあるので、UtteranceSegmenter からは区別がつかない。
"""
from __future__ import annotations

import asyncio
import logging

import numpy as np

log = logging.getLogger(__name__)


class RemoteMic:
    """WebSocket で届く PCM(s16le mono) をマイク入力として流す。

    サーバの受信ハンドラ（同じイベントループ）から feed() が呼ばれるので、
    Mic のような call_soon_threadsafe は要らない。
    """

    def __init__(
        self,
        server,
        sample_rate: int = 16000,
        frame_samples: int = 512,
        gain: float = 1.0,
        max_queue: int = 64,
    ) -> None:
        self.server = server
        self.sample_rate = sample_rate
        self.frame_samples = frame_samples
        self.gain = gain
        self.queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=max_queue)

        # フレーム境界に満たない端数。ファームは frame_samples ちょうどで
        # 送ってくるが、届き方に依存しないようにここで組み直す
        self._resid = np.empty(0, dtype=np.float32)
        self._paused = False
        self._dropped = 0
        self._got_first = False

    # --- Mic と同じ形 -----------------------------------------------------
    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        """再生・処理中は耳を閉じる。

        半二重なので、こちらが喋る前にロボットのマイクを実際に止めさせる
        必要がある。PC 側で捨てるだけでは I2S をスピーカーに明け渡せない。
        """
        value = bool(value)
        if value == self._paused:
            return
        self._paused = value
        self._resid = np.empty(0, dtype=np.float32)
        self.server.set_mic(not value, rate=self.sample_rate)

    def start(self) -> None:
        self.server.on_audio(self.feed)
        self.server.set_mic(True, rate=self.sample_rate)
        log.info(
            "remote mic started (%d Hz, %d samples/frame, gain=%.1f)",
            self.sample_rate, self.frame_samples, self.gain,
        )

    def stop(self) -> None:
        self.server.set_mic(False, rate=self.sample_rate)
        self.server.on_audio(None)

    async def frames(self):
        while True:
            yield await self.queue.get()

    # --- 受信 -------------------------------------------------------------
    def feed(self, data: bytes) -> None:
        """CoreS3 から届いた PCM。サーバの受信側から呼ばれる。"""
        if self._paused or len(data) < 2:
            return
        if not self._got_first:
            self._got_first = True
            log.info("CoreS3 のマイクから音が届きはじめました")

        # 奇数バイトで切れて届いても落ちないようにする
        pcm = np.frombuffer(data[: len(data) // 2 * 2], dtype="<i2")
        buf = pcm.astype(np.float32) / 32768.0
        if self.gain != 1.0:
            buf = np.clip(buf * self.gain, -1.0, 1.0)

        if self._resid.size:
            buf = np.concatenate((self._resid, buf))

        n = self.frame_samples
        whole = len(buf) // n
        for i in range(whole):
            self._put(buf[i * n : (i + 1) * n])
        self._resid = buf[whole * n :].copy()

    def _put(self, frame: np.ndarray) -> None:
        try:
            self.queue.put_nowait(frame)
        except asyncio.QueueFull:
            # 消費が追いつかない場合は古い方を捨てる（遅延を溜めない）。
            # paused 中は積まないので、ここに来るのは本当に異常な状態だけ
            self._dropped += 1
            if self._dropped % 50 == 1:
                log.warning(
                    "CoreS3 マイクの取りこぼし: イベントループが詰まっています "
                    "(累計 %d フレーム / %.1f 秒ぶん)",
                    self._dropped, self._dropped * self.frame_samples / self.sample_rate,
                )
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(frame)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass
