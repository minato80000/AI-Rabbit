"""faster-whisper による音声認識。

CTranslate2 ベースなので torch には依存しない。

GPU で動かすと CPU の 1/8 程度の時間で済む（実測 976ms -> 114ms）。
VRAM は base モデルで 200MB 強しか使わず、LLM と同居しても
LLM 側の GPU/CPU 配分は変わらなかった。既定は cuda、失敗したら cpu に落ちる。
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


def _ensure_cuda_dlls() -> None:
    """nvidia の pip パッケージが置いた DLL を探索パスに通す。

    Windows では cuBLAS / cuDNN が PATH 上にないと、モデルのロードは通るのに
    最初の推論で「cublas64_12.dll is not found」で落ちる。
    os.add_dll_directory では CTranslate2 の遅延ロードに効かないため PATH を触る。
    """
    try:
        import nvidia
    except ImportError:
        return
    # nvidia-* は名前空間パッケージなので __file__ は None。__path__ を使う
    roots = [Path(p).resolve() for p in getattr(nvidia, "__path__", [])]
    dirs = [str(d) for r in roots for d in r.glob("*/bin") if d.is_dir()]
    if not dirs:
        return
    current = os.environ.get("PATH", "")
    missing = [d for d in dirs if d not in current]
    if missing:
        os.environ["PATH"] = os.pathsep.join(missing) + os.pathsep + current
        log.debug("CUDA DLL パスを追加: %s", missing)


class Whisper:
    def __init__(
        self,
        model: str = "base",
        device: str = "cuda",
        compute_type: str = "int8_float16",
        language: str = "ja",
        initial_prompt: str | None = None,
        beam_size: int = 1,
        no_speech_threshold: float = 0.6,
        hallucination_patterns: list[str] | None = None,
    ) -> None:
        self.language = language
        # 1 は貪欲法で最速。GPU なら 5 にしても余裕があり、精度が上がる
        self.beam_size = beam_size
        # これを超えた区間は捨てる。whisper は無音やノイズを渡されると
        # 「ご視聴ありがとうございました」のような字幕由来の幻聴を返すが、
        # そのとき no_speech_prob は 0.91 以上になる（実測）。
        # 本物の音声は 0.08 以下だったので、間を取って 0.6 を既定とする。
        self.no_speech_threshold = no_speech_threshold
        # no_speech_prob をすり抜ける幻聴のための2層目。
        # whisper は字幕を大量に学習しており、動画の締めの決まり文句を返すことがある。
        # モデルが自信を持って出すと確度では弾けないので、文字列でも見る。
        # ロボットに話しかける言葉として出る可能性が低いものだけを入れること。
        self.hallucination_patterns = list(hallucination_patterns or [])
        # 固有名詞を先に見せておくと綴りが安定する。
        # これがないと「ウサちゃん」が「おさちゃん」になり、名前を呼んでも反応しない。
        self.initial_prompt = initial_prompt

        self.device, self.compute_type = self._load(model, device, compute_type)

    def _load(self, model: str, device: str, compute_type: str) -> tuple[str, str]:
        from faster_whisper import WhisperModel

        if device == "cuda":
            _ensure_cuda_dlls()

        t0 = time.perf_counter()
        try:
            self.model = WhisperModel(model, device=device, compute_type=compute_type)
            # ロードが通っても最初の推論で落ちることがあるので、ここで一度回す
            self._transcribe_sync(np.zeros(16000, dtype=np.float32))
        except Exception as e:
            if device != "cuda":
                raise
            log.warning("GPU が使えないので CPU にフォールバックします: %s", e)
            device, compute_type = "cpu", "int8"
            self.model = WhisperModel(model, device=device, compute_type=compute_type)

        log.info(
            "whisper loaded: %s / %s / %s (%.1fs)",
            model, device, compute_type, time.perf_counter() - t0,
        )
        return device, compute_type

    def _transcribe_sync(self, audio: np.ndarray) -> str:
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=False,     # 区間切り出しは Silero VAD 側で済んでいる
            condition_on_previous_text=False,  # 前文脈の引きずりによる幻聴を防ぐ
            initial_prompt=self.initial_prompt,
        )

        # faster-whisper 組み込みの no_speech_threshold は avg_logprob との
        # AND 判定なので、logprob が正常な幻聴は通り抜ける。単独で判定する。
        kept: list[str] = []
        for seg in segments:
            text = seg.text.strip()
            if seg.no_speech_prob > self.no_speech_threshold:
                log.info(
                    "幻聴とみなして破棄（確度）: %r (no_speech_prob=%.3f)",
                    text, seg.no_speech_prob,
                )
                continue
            hit = self._matches_hallucination(text)
            if hit is not None:
                log.info(
                    "幻聴とみなして破棄（既知の文言 %r）: %r (no_speech_prob=%.3f)",
                    hit, text, seg.no_speech_prob,
                )
                continue
            kept.append(seg.text)
        return "".join(kept).strip()

    def _matches_hallucination(self, text: str) -> str | None:
        """既知の幻聴に該当すればそのパターンを返す。"""
        for pat in self.hallucination_patterns:
            if pat and pat in text:
                return pat
        return None

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
