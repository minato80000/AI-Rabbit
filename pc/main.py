"""ウサちゃんロボ 対話ループ（Step 1: PC 単体）

    python -m pc.main                     通常起動
    python -m pc.main --text "こんにちは"   マイクを使わず LLM+TTS だけ試す
    python -m pc.main --list-devices       オーディオデバイス一覧
    python -m pc.main --list-speakers      VOICEVOX の話者一覧
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

import yaml

from .audio.mic import Mic
from .audio.player import Player
from .audio.vad import UtteranceSegmenter
from .llm import client as llm_client
from .llm.sentence import SentenceStreamer
from .state import Emotion, State, StateMachine
from .stt.whisper import Whisper
from .tts.voicevox import VoiceVox
from .wake import WakeDetector

log = logging.getLogger("rabbit")
ROOT = Path(__file__).resolve().parent


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _strip_comments(text: str) -> str:
    """編集者向けの HTML コメントをプロンプトから除く。"""
    out: list[str] = []
    depth = 0
    i = 0
    while i < len(text):
        if text.startswith("<!--", i):
            depth += 1
            i += 4
        elif text.startswith("-->", i):
            depth = max(0, depth - 1)
            i += 3
        else:
            if depth == 0:
                out.append(text[i])
            i += 1
    return "".join(out).strip()


def load_persona(cfg: dict) -> str:
    """ペルソナを読む。

    公開用のベースファイルに、ローカル専用ファイルがあれば追記する。
    **原作のセリフなど公開したくない内容はローカル側に置く。**
    ローカル側は .gitignore と pre-commit フックの両方で保護されており、
    リポジトリには入らない。存在しなければベースだけで動く。
    """
    pcfg = cfg["persona"]
    base_path = ROOT / pcfg["file"]
    parts = [_strip_comments(base_path.read_text(encoding="utf-8"))]

    local_name = pcfg.get("local_file")
    if local_name:
        local_path = ROOT / local_name
        if local_path.exists():
            parts.append(_strip_comments(local_path.read_text(encoding="utf-8")))
            log.info("ペルソナ: %s + %s（ローカル専用）", base_path.name, local_path.name)
        else:
            log.info(
                "ペルソナ: %s のみ。%s を作るとセリフ例を追加できます（非公開）",
                base_path.name, local_path.name,
            )

    return "\n\n".join(p for p in parts if p).strip()


class Rabbit:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.state = StateMachine()
        self.state.subscribe(self._on_state)
        self.persona = load_persona(cfg)

        self.wake = WakeDetector(
            words=cfg["wake"]["words"],
            conversation_window_sec=cfg["wake"]["conversation_window_sec"],
            fuzzy_distance=cfg["wake"].get("fuzzy_distance", 1),
        )
        self.llm = llm_client.build(cfg["llm"], self.persona)
        self.tts = VoiceVox(**cfg["tts"])
        self.player = Player(sample_rate=24000, device=cfg["audio"]["output_device"])
        self.stt: Whisper | None = None
        self.mic: Mic | None = None
        self.segmenter: UtteranceSegmenter | None = None

    def _on_state(self, state: State, emotion: Emotion) -> None:
        # Step 4 ではここから CoreS3 へ state を push する
        log.debug("state -> %s / %s", state.value, emotion.value)

    async def preflight(self) -> None:
        print("起動前チェック...", flush=True)
        try:
            ver = await self.tts.health()
            elapsed = await self.tts.prewarm()
            print(f"  VOICEVOX : OK (v{ver} / 話者{self.tts.speaker} 準備 {elapsed:.1f}s)")
        except Exception as e:
            raise SystemExit(
                f"  VOICEVOX : NG ({e})\n\n"
                f"  VOICEVOX が起動していません。アプリまたは VOICEVOX ENGINE を\n"
                f"  立ち上げてください（{self.cfg['tts']['host']}）。"
            )
        try:
            model = await self.llm.health()
            print(f"  LLM      : OK ({model})")
        except Exception as e:
            raise SystemExit(f"  LLM      : NG ({e})")

    def load_stt(self) -> None:
        print("  Whisper  : 読み込み中...", end="", flush=True)
        self.stt = Whisper(**self.cfg["stt"])
        print(" OK")

    # --- 発話 -------------------------------------------------------------
    async def _emit(self, text: str, emotion: Emotion) -> None:
        self.state.set(State.SPEAKING, emotion)
        print(f"  ウサちゃん> {text}")
        pcm = await self.tts.synth(text)
        self.player.enqueue(pcm)   # ここで初めて音が出る

    async def say(self, text: str, emotion: Emotion = Emotion.NEUTRAL) -> None:
        """固定セリフを喋る。"""
        await self._emit(text, emotion)
        await self.player.drain()
        self.state.set(State.IDLE)

    async def respond(self, query: str) -> None:
        """LLM の返答を文単位で合成・再生する。全文は待たない。"""
        self.state.set(State.THINKING)
        t0 = time.perf_counter()
        streamer = SentenceStreamer()
        spoken: list[str] = []

        # 第1文が揃った時刻と、実際に音が出はじめた時刻は別物。
        # 前者は LLM の速さ、後者は TTS 込みの体感レイテンシを表す。
        first_sentence_at: float | None = None
        first_audio_at: float | None = None

        async def emit(text: str, emotion: Emotion) -> None:
            nonlocal first_sentence_at, first_audio_at
            if first_sentence_at is None:
                first_sentence_at = time.perf_counter()
            spoken.append(text)
            await self._emit(text, emotion)
            if first_audio_at is None:
                first_audio_at = time.perf_counter()

        try:
            async for delta in self.llm.stream(query):
                if self.cfg["debug"]["print_llm_raw"]:
                    print(delta, end="", flush=True)
                for text, emotion in streamer.feed(delta):
                    await emit(text, emotion)
            for text, emotion in streamer.flush():
                await emit(text, emotion)
        except Exception:
            log.exception("LLM 応答中にエラー")
            spoken = []
            await self._emit("あれ、うまく考えられないのだ", Emotion.PUZZLED)

        await self.player.drain()
        self.state.set(State.IDLE)

        if spoken:
            self.llm.record(query, "".join(spoken))
        if first_audio_at is not None and first_sentence_at is not None:
            log.info(
                "第1文まで %.2fs / 初音出しまで %.2fs / 再生完了まで %.2fs",
                first_sentence_at - t0,
                first_audio_at - t0,
                time.perf_counter() - t0,
            )

    # --- メインループ -----------------------------------------------------
    def _flush_input(self) -> None:
        """再生中に溜まったマイク入力を捨て、VAD を初期化する。"""
        if self.mic is None or self.segmenter is None:
            return
        while not self.mic.queue.empty():
            try:
                self.mic.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.segmenter.reset()

    async def handle(self, audio) -> None:
        self.state.set(State.THINKING)
        text = await self.stt.transcribe(audio)
        if not text:
            self.state.set(State.IDLE)
            return

        if self.cfg["debug"]["print_transcript"]:
            mark = "*" if self.wake.conversation_active else " "
            print(f"{mark} あなた   > {text}")

        result = self.wake.check(text)
        if not result.addressed:
            self.state.set(State.IDLE)
            return

        self.wake.touch()
        if result.query:
            await self.respond(result.query)
        else:
            await self.say(self.cfg["wake"]["greeting"])
        self.wake.touch()  # 応答にかかった時間ぶん会話ウィンドウを延ばす

    async def run(self) -> None:
        acfg = self.cfg["audio"]
        self.mic = Mic(
            asyncio.get_running_loop(),
            sample_rate=acfg["sample_rate"],
            frame_samples=acfg["frame_samples"],
            device=acfg["input_device"],
        )
        self.segmenter = UtteranceSegmenter(self.mic, **self.cfg["vad"])

        if self.cfg["behavior"]["barge_in"]:
            log.warning(
                "barge_in: true ですが Step 1 では未実装です（Step 5 で対応）。"
                "PC のマイクとスピーカーが同じ部屋にあるため、有効化には"
                "音響エコーの処理が必要です。"
            )

        self.player.start()
        self.mic.start()

        words = " / ".join(self.cfg["wake"]["words"])
        window = self.cfg["wake"]["conversation_window_sec"]
        print()
        print(f"  待機中。「{words}」と呼びかけてください。")
        print(f"  会話が始まると {window:.0f} 秒間は呼びかけ不要です。")
        print("  終了は Ctrl+C。")
        print()

        try:
            self.state.set(State.IDLE)
            async for audio in self.segmenter.utterances():
                # 処理・発話中はマイクを閉じる（自分の声を拾わないため）
                self.segmenter.enabled = False
                try:
                    await self.handle(audio)
                finally:
                    self._flush_input()
                    self.segmenter.enabled = True
        finally:
            self.mic.stop()
            self.player.stop()

    async def aclose(self) -> None:
        await self.llm.aclose()
        await self.tts.aclose()


# --- サブコマンド ---------------------------------------------------------
def list_devices() -> None:
    import sounddevice as sd

    print(sd.query_devices())


async def list_speakers(cfg: dict) -> None:
    tts = VoiceVox(**cfg["tts"])
    try:
        for sid, name in await tts.speakers():
            print(f"  {sid:4d}  {name}")
    finally:
        await tts.aclose()


async def text_mode(cfg: dict, text: str) -> None:
    """マイクを使わず、LLM から再生までを試す。"""
    rabbit = Rabbit(cfg)
    try:
        await rabbit.preflight()
        rabbit.player.start()
        print(f"\n  あなた   > {text}")
        await rabbit.respond(text)
        rabbit.player.stop()
    finally:
        await rabbit.aclose()


async def check_mic_mode(cfg: dict, seconds: float, wav: Path | None) -> None:
    from .diagnose import check_mic

    await check_mic(cfg, seconds, wav)


async def run_mode(cfg: dict) -> None:
    rabbit = Rabbit(cfg)
    try:
        await rabbit.preflight()
        rabbit.load_stt()
        await rabbit.run()
    finally:
        await rabbit.aclose()


def main() -> int:
    ap = argparse.ArgumentParser(description="ウサちゃんロボ 対話ループ")
    ap.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    ap.add_argument("--text", help="マイクを使わずこのテキストで応答を試す")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--list-speakers", action="store_true")
    ap.add_argument("--check-mic", action="store_true",
                    help="マイクを録音して、音量・VAD・モデル別の認識結果を診断する")
    ap.add_argument("--seconds", type=float, default=6.0,
                    help="--check-mic の録音秒数")
    ap.add_argument("--wav", type=Path,
                    help="録音済み WAV を解析する（--check-mic と併用。録り直し不要）")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)

    if args.list_devices:
        list_devices()
        return 0

    cfg = load_config(args.config)
    try:
        if args.check_mic or args.wav:
            asyncio.run(check_mic_mode(cfg, args.seconds, args.wav))
        elif args.list_speakers:
            asyncio.run(list_speakers(cfg))
        elif args.text:
            asyncio.run(text_mode(cfg, args.text))
        else:
            asyncio.run(run_mode(cfg))
    except KeyboardInterrupt:
        print("\n  またね。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
