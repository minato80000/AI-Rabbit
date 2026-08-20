"""Silero VAD による発話区間の切り出し。

無音を捨てて、発話が終わったタイミングで音声を1本の配列として吐く。
先頭が切れないよう、発話検出の直前フレームも含める（プリロール）。
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Callable

import numpy as np
import torch

log = logging.getLogger(__name__)

PREROLL_MS = 300


def _load_model():
    from silero_vad import load_silero_vad

    try:
        model = load_silero_vad(onnx=True)
        log.info("Silero VAD loaded (onnx)")
    except Exception as e:  # onnxruntime が使えない環境では jit にフォールバック
        log.warning("onnx VAD unavailable (%s), falling back to jit", e)
        model = load_silero_vad()
        log.info("Silero VAD loaded (jit)")
    return model


class UtteranceSegmenter:
    def __init__(
        self,
        mic,
        threshold: float = 0.5,
        min_speech_ms: int = 250,
        hangover_ms: int = 400,
        max_utterance_sec: float = 15.0,
        on_speech_start: Callable[[], None] | None = None,
    ) -> None:
        self.mic = mic
        self.model = _load_model()
        self.threshold = threshold
        self.on_speech_start = on_speech_start

        sr = mic.sample_rate
        fs = mic.frame_samples
        self.frame_ms = 1000.0 * fs / sr
        self.min_speech_frames = max(1, int(min_speech_ms / self.frame_ms))
        self.hangover_frames = max(1, int(hangover_ms / self.frame_ms))
        self.max_frames = int(max_utterance_sec * 1000 / self.frame_ms)
        self.preroll_frames = max(1, int(PREROLL_MS / self.frame_ms))

        # False の間はフレームを捨てる（再生中にマイクを閉じる用途）
        self.enabled = True

    def reset(self) -> None:
        self.model.reset_states()

    async def utterances(self) -> AsyncIterator[np.ndarray]:
        preroll: list[np.ndarray] = []
        speech: list[np.ndarray] = []
        in_speech = False
        silence_run = 0

        async for frame in self.mic.frames():
            if not self.enabled:
                if in_speech or speech:
                    in_speech = False
                    speech.clear()
                    silence_run = 0
                    self.reset()
                preroll.clear()
                continue

            prob = float(self.model(torch.from_numpy(frame), self.mic.sample_rate).item())
            voiced = prob >= self.threshold

            if not in_speech:
                preroll.append(frame)
                if len(preroll) > self.preroll_frames:
                    preroll.pop(0)
                if voiced:
                    in_speech = True
                    silence_run = 0
                    speech = list(preroll)
                    preroll.clear()
                    if self.on_speech_start is not None:
                        self.on_speech_start()
                continue

            speech.append(frame)
            silence_run = 0 if voiced else silence_run + 1

            too_long = len(speech) >= self.max_frames
            ended = silence_run >= self.hangover_frames

            if ended or too_long:
                in_speech = False
                self.reset()
                # hangover 分の無音は末尾から落とす
                voiced_frames = len(speech) - (silence_run if ended else 0)
                if voiced_frames >= self.min_speech_frames:
                    yield np.concatenate(speech[:voiced_frames])
                else:
                    log.debug("utterance too short (%d frames), discarded", voiced_frames)
                speech = []
                silence_run = 0
