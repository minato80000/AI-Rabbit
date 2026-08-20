"""faster-whisper による音声認識。

CTranslate2 ベースなので torch には依存しない。
device は config で切り替える（GPU は LLM に明け渡すため既定は cpu）。
"""
from __future__ import annotations

import asyncio
import logging
import time

import numpy as np

log = logging.getLogger(__name__)


class Whisper:
    def __init__(
        self,
        model: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "ja",
    ) -> None:
        from faster_whisper import WhisperModel

        t0 = time.perf_counter()
        self.model = WhisperModel(model, device=device, compute_type=compute_type)
        self.language = language
        log.info(
            "whisper loaded: %s / %s / %s (%.1fs)",
            model, device, compute_type, time.perf_counter() - t0,
        )

    def _transcribe_sync(self, audio: np.ndarray) -> str:
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=1,          # 対話用途では貪欲法で十分。速度優先
            vad_filter=False,     # 区間切り出しは Silero VAD 側で済んでいる
            condition_on_previous_text=False,  # 前文脈の引きずりによる幻聴を防ぐ
        )
        return "".join(s.text for s in segments).strip()

    async def transcribe(self, audio: np.ndarray) -> str:
        """float32 mono 16kHz を受け取って文字列を返す。"""
        loop = asyncio.get_running_loop()
        t0 = time.perf_counter()
        text = await loop.run_in_executor(None, self._transcribe_sync, audio)
        log.debug(
            "stt: %.0fms for %.1fs audio -> %r",
            (time.perf_counter() - t0) * 1000, len(audio) / 16000, text,
        )
        return text
