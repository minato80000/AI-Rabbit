"""VOICEVOX ENGINE (localhost:50021) による音声合成。

1文ずつ叩く。全文をまとめて合成すると初音出しが遅れて設計が壊れる。
"""
from __future__ import annotations

import io
import logging
import time
import wave

import httpx
import numpy as np

log = logging.getLogger(__name__)


class VoiceVox:
    def __init__(
        self,
        host: str = "http://127.0.0.1:50021",
        speaker: int = 1,
        speed: float = 1.0,
        pitch: float = 0.0,
        intonation: float = 1.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.speaker = speaker
        self.speed = speed
        self.pitch = pitch
        self.intonation = intonation
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=3.0))
        self.sample_rate = 24000

    async def health(self) -> str:
        r = await self._client.get(f"{self.host}/version")
        r.raise_for_status()
        return r.text.strip().strip('"')

    async def speakers(self) -> list[tuple[int, str]]:
        """話者ID一覧。原作再現に合う声を選ぶときに使う。"""
        r = await self._client.get(f"{self.host}/speakers")
        r.raise_for_status()
        out: list[tuple[int, str]] = []
        for s in r.json():
            for style in s.get("styles", []):
                out.append((style["id"], f"{s['name']} / {style['name']}"))
        return out

    async def synth(self, text: str) -> np.ndarray:
        """テキスト1文を int16 mono PCM に変換する。"""
        t0 = time.perf_counter()

        q = await self._client.post(
            f"{self.host}/audio_query",
            params={"text": text, "speaker": self.speaker},
        )
        q.raise_for_status()
        query = q.json()
        query["speedScale"] = self.speed
        query["pitchScale"] = self.pitch
        query["intonationScale"] = self.intonation
        # 前後の無音は詰める（文ごとに合成するので溜まると間延びする）
        query["prePhonemeLength"] = 0.0
        query["postPhonemeLength"] = 0.05

        s = await self._client.post(
            f"{self.host}/synthesis",
            params={"speaker": self.speaker},
            json=query,
        )
        s.raise_for_status()

        with wave.open(io.BytesIO(s.content), "rb") as w:
            self.sample_rate = w.getframerate()
            frames = w.readframes(w.getnframes())
            pcm = np.frombuffer(frames, dtype=np.int16)
            if w.getnchannels() == 2:
                pcm = pcm.reshape(-1, 2).mean(axis=1).astype(np.int16)

        log.debug(
            "tts: %.0fms for %d chars -> %.2fs audio",
            (time.perf_counter() - t0) * 1000, len(text), len(pcm) / self.sample_rate,
        )
        return pcm

    async def aclose(self) -> None:
        await self._client.aclose()
