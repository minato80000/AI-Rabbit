"""マイクと音声認識の診断。

    python -m pc.main --check-mic

実マイクの音は合成音声よりずっと難しい。聞き取れない原因が
「マイクのレベル」「VAD の切り出し」「STT モデルの力不足」のどれなのかを
切り分けるための道具。録音した WAV は recordings/ に残す（非公開）。
"""
from __future__ import annotations

import asyncio
import math
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd

from .audio.vad import UtteranceSegmenter
from .stt.whisper import Whisper

ROOT = Path(__file__).resolve().parent
REC_DIR = ROOT.parent / "recordings"


def _dbfs(x: float) -> float:
    return -math.inf if x <= 0 else 20.0 * math.log10(x)


class _ArrayMic:
    """録音済み配列をフレームとして流す。VAD をオフラインで回すため。"""

    def __init__(self, data: np.ndarray, sample_rate: int, frame_samples: int) -> None:
        self.data = data
        self.sample_rate = sample_rate
        self.frame_samples = frame_samples

    async def frames(self):
        n = self.frame_samples
        for i in range(0, len(self.data) - n + 1, n):
            yield self.data[i : i + n]
        for _ in range(60):  # 末尾の発話を確定させるための無音
            yield np.zeros(n, dtype=np.float32)


def record(seconds: float, sample_rate: int, device) -> np.ndarray:
    print(f"  録音します（{seconds:.0f}秒）。「ウサちゃん、今日はいい天気だね」のように話しかけてください。")
    for i in (3, 2, 1):
        print(f"    {i}...", flush=True)
        time.sleep(1)
    print("  >>> どうぞ <<<", flush=True)
    buf = sd.rec(int(seconds * sample_rate), samplerate=sample_rate,
                 channels=1, dtype="float32", device=device)
    sd.wait()
    print("  録音終了")
    return buf[:, 0].copy()


def report_levels(audio: np.ndarray, sample_rate: int) -> None:
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio ** 2)))
    clipped = int(np.sum(np.abs(audio) >= 0.999))

    # 32ms ごとの RMS からノイズフロアと発話レベルを推定する
    n = int(sample_rate * 0.032)
    frames = audio[: len(audio) // n * n].reshape(-1, n)
    frame_rms = np.sqrt(np.mean(frames ** 2, axis=1))
    floor = float(np.percentile(frame_rms, 20))
    speech = float(np.percentile(frame_rms, 95))
    snr = _dbfs(speech) - _dbfs(floor)

    print()
    print("  === 音量 ===")
    print(f"    ピーク       : {_dbfs(peak):6.1f} dBFS")
    print(f"    平均(RMS)    : {_dbfs(rms):6.1f} dBFS")
    print(f"    ノイズフロア : {_dbfs(floor):6.1f} dBFS")
    print(f"    発話レベル   : {_dbfs(speech):6.1f} dBFS")
    print(f"    推定 SNR     : {snr:6.1f} dB")
    if clipped:
        print(f"    クリップ     : {clipped} サンプル")

    print()
    print("  === 判定 ===")
    ok = True
    if peak < 0.03:
        print("    NG マイクの音が非常に小さい。Windows のマイク音量を上げるか、近づいて話してください")
        ok = False
    elif peak < 0.1:
        print("    △  音が小さめ。マイク音量を上げると認識が改善する可能性があります")
        ok = False
    if clipped > 10:
        print("    NG 音が割れている（クリップ）。マイク音量を下げてください")
        ok = False
    if snr < 15:
        print(f"    △  SNR {snr:.0f}dB は低め。周囲の騒音が多いか、マイクが遠い可能性があります")
        ok = False
    if ok:
        print("    OK 音量・SNR とも良好です")


def save_wav(audio: np.ndarray, sample_rate: int) -> Path:
    REC_DIR.mkdir(exist_ok=True)
    path = REC_DIR / f"mic-{datetime.now():%Y%m%d-%H%M%S}.wav"
    pcm = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return path


async def segment(audio: np.ndarray, cfg: dict) -> list[np.ndarray]:
    mic = _ArrayMic(audio, cfg["audio"]["sample_rate"], cfg["audio"]["frame_samples"])
    seg = UtteranceSegmenter(mic, **cfg["vad"])
    out = []
    async for utt in seg.utterances():
        out.append(utt)
    return out


async def compare_models(
    utterances: list[np.ndarray], cfg: dict, models: list[str], beams: list[int]
) -> None:
    for name in models:
        scfg = dict(cfg["stt"])
        scfg["model"] = name
        print(f"    {name} を読み込み中...", end="", flush=True)
        t0 = time.perf_counter()
        try:
            stt = Whisper(**scfg)
        except Exception as e:
            print(f" 失敗 ({type(e).__name__}: {e})")
            continue
        print(f" {time.perf_counter() - t0:.1f}s ({stt.device})")

        # モデルは1回だけ読み、beam だけ変えて回す
        for beam in beams:
            stt.beam_size = beam
            print(f"      [beam={beam}]")
            for i, utt in enumerate(utterances, 1):
                t0 = time.perf_counter()
                text = await stt.transcribe(utt)
                el = (time.perf_counter() - t0) * 1000
                print(f"        {i}. {el:5.0f}ms  {text}")
        del stt


def load_wav(path: Path, sample_rate: int) -> np.ndarray:
    """保存済みの録音を読む。設定を変えて再解析するとき用。"""
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != sample_rate:
            raise SystemExit(
                f"  {path.name} は {w.getframerate()}Hz です。"
                f"{sample_rate}Hz の録音が必要です。"
            )
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if w.getnchannels() == 2:
            pcm = pcm.reshape(-1, 2).mean(axis=1)
    return pcm.astype(np.float32) / 32768.0


async def check_mic(cfg: dict, seconds: float = 6.0, wav: Path | None = None) -> None:
    sr = cfg["audio"]["sample_rate"]
    device = cfg["audio"]["input_device"]

    if wav is not None:
        print("=== 録音ファイルの解析 ===")
        print(f"  ファイル: {wav}")
        audio = load_wav(wav, sr)
        path = wav
        report_levels(audio, sr)
    else:
        print("=== マイク診断 ===")
        print(f"  入力デバイス: {device if device is not None else '(既定)'}")
        print(f"  サンプルレート: {sr} Hz")
        print()
        audio = record(seconds, sr, device)
        report_levels(audio, sr)
        path = save_wav(audio, sr)
        print()
        print(f"  録音を保存: {path}")

    print()
    print("  === VAD の切り出し ===")
    utterances = await segment(audio, cfg)
    if not utterances:
        print("    NG 発話が1つも検出されませんでした。")
        print("       音量が小さすぎるか、vad.threshold が高すぎる可能性があります。")
        print(f"       現在の threshold={cfg['vad']['threshold']}。0.3 程度まで下げて再試行してください。")
        return
    total = sum(len(u) for u in utterances) / sr
    print(f"    {len(utterances)} 本を検出（合計 {total:.1f}秒 / 録音 {len(audio)/sr:.1f}秒）")
    for i, u in enumerate(utterances, 1):
        print(f"      {i}. {len(u)/sr:.2f}秒")

    print()
    print("  === モデル別の認識結果 ===")
    await compare_models(utterances, cfg, ["base", "small", "medium"], [1, 5])

    print()
    print("  === 次にすること ===")
    print("    上の結果を見て、一番正確なモデルを config.yaml の stt.model に設定してください。")
    print("    beam=5 は精度が上がる代わりに少し遅くなります。")
    print(f"    録音は {path} に残っているので、後から再解析できます。")
