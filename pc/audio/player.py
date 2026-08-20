"""再生キュー。

Step 1 では PC のスピーカーへ流す。Step 3 で CoreS3 への WebSocket 送信に
差し替えるため、enqueue / flush / drain のインターフェースだけを使うこと。
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)


class Player:
    def __init__(self, sample_rate: int = 24000, device: int | str | None = None) -> None:
        self.sample_rate = sample_rate
        self.device = device
        self._chunks: queue.Queue[np.ndarray] = queue.Queue()
        self._residual = np.zeros(0, dtype=np.int16)
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._stream: sd.OutputStream | None = None

    def _callback(self, outdata, frames, time_info, status) -> None:  # 別スレッド
        if status:
            log.debug("player status: %s", status)
        out = np.zeros(frames, dtype=np.int16)
        filled = 0
        with self._lock:
            while filled < frames:
                if self._residual.size == 0:
                    try:
                        self._residual = self._chunks.get_nowait()
                    except queue.Empty:
                        break
                take = min(frames - filled, self._residual.size)
                out[filled : filled + take] = self._residual[:take]
                self._residual = self._residual[take:]
                filled += take
            if self._residual.size == 0 and self._chunks.empty():
                self._idle.set()
        outdata[:, 0] = out

    def start(self) -> None:
        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            blocksize=0,
            channels=1,
            dtype="int16",
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()
        log.info("player started (%d Hz)", self.sample_rate)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def enqueue(self, pcm: np.ndarray) -> None:
        """int16 mono PCM を再生キューに積む。"""
        if pcm.dtype != np.int16:
            pcm = pcm.astype(np.int16)
        with self._lock:
            self._idle.clear()
            self._chunks.put(pcm)

    def flush(self) -> None:
        """barge-in。キューと再生中のバッファを即破棄する。"""
        with self._lock:
            while True:
                try:
                    self._chunks.get_nowait()
                except queue.Empty:
                    break
            self._residual = np.zeros(0, dtype=np.int16)
            self._idle.set()

    @property
    def busy(self) -> bool:
        return not self._idle.is_set()

    async def drain(self) -> None:
        """再生し終わるまで待つ。"""
        while self.busy:
            await asyncio.sleep(0.02)
