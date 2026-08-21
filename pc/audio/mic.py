"""マイク入力。

sounddevice のコールバックは別スレッドで回るので、asyncio 側へは
call_soon_threadsafe で受け渡す。
"""
from __future__ import annotations

import asyncio
import logging

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)


class Mic:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        sample_rate: int = 16000,
        frame_samples: int = 512,
        device: int | str | None = None,
        max_queue: int = 64,
    ) -> None:
        self.loop = loop
        self.sample_rate = sample_rate
        self.frame_samples = frame_samples
        self.device = device
        self.queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=max_queue)
        self._stream: sd.InputStream | None = None
        self._dropped = 0
        # 処理中・発話中は聞かない。True の間はコールバックで即捨てる。
        # キューに積んでから捨てると、溢れるたびに警告が出て紛らわしいうえ、
        # フレームごとにスレッド間の受け渡しが走って無駄になる。
        self.paused = False

    def _callback(self, indata, frames, time_info, status) -> None:  # 別スレッド
        if status:
            log.debug("mic status: %s", status)
        if self.paused:
            return  # 聞いていないので、そもそも積まない
        frame = indata[:, 0].copy()  # float32 mono
        try:
            self.loop.call_soon_threadsafe(self._put, frame)
        except RuntimeError:
            pass  # ループが閉じている（終了処理中）

    def _put(self, frame: np.ndarray) -> None:
        try:
            self.queue.put_nowait(frame)
        except asyncio.QueueFull:
            # 消費が追いつかない場合は古い方を捨てる（遅延を溜めない）。
            # paused 中は積まないので、ここに来るのは「聞いているのに処理が
            # 追いついていない」場合だけ。つまり本当に異常な状態。
            self._dropped += 1
            if self._dropped % 50 == 1:
                log.warning(
                    "マイクの取りこぼし: イベントループが詰まっています "
                    "(累計 %d フレーム / %.1f 秒ぶん)",
                    self._dropped, self._dropped * self.frame_samples / self.sample_rate,
                )
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(frame)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    def start(self) -> None:
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame_samples,
            channels=1,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()
        log.info("mic started (%d Hz, %d samples/frame)", self.sample_rate, self.frame_samples)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    async def frames(self):
        while True:
            yield await self.queue.get()
