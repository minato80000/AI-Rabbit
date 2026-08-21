r"""CoreS3 の代わりをする WebSocket クライアント。

実機のファームを書く前に、プロトコルと音声転送を検証するための道具。
受け取った音声を PC のスピーカーで鳴らし、状態変化を顔文字で表示する。

    .venv\Scripts\python tools\dummy_core.py
    .venv\Scripts\python tools\dummy_core.py --no-play --save out.wav
    .venv\Scripts\python tools\dummy_core.py --touch-after 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np
import websockets

FACES = {
    ("idle", "neutral"): "( ･ω･ )",
    ("listening", "neutral"): "( ･ω･)ﾉ",
    ("thinking", "neutral"): "( ･ω･)？",
    ("speaking", "neutral"): "( ･ω･)b",
    ("speaking", "happy"): "( ^ω^ )",
    ("speaking", "puzzled"): "( ･ω･;)",
    ("speaking", "surprised"): "( ﾟωﾟ )",
}


def face(state: str, emotion: str) -> str:
    return FACES.get((state, emotion), FACES.get((state, "neutral"), "( ･ω･ )"))


class DummyCore:
    def __init__(self, play: bool, save: Path | None) -> None:
        self.play = play
        self.save = save
        self.rate = 24000
        self.buf: list[np.ndarray] = []
        self.received = 0
        self.begin_at = 0.0
        self.stream = None

    def _open_stream(self) -> None:
        if not self.play:
            return
        import sounddevice as sd

        self.stream = sd.OutputStream(
            samplerate=self.rate, channels=1, dtype="int16", blocksize=0
        )
        self.stream.start()

    def _close_stream(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def on_audio(self, data: bytes) -> None:
        pcm = np.frombuffer(data, dtype=np.int16)
        self.received += len(data)
        self.buf.append(pcm)
        if self.stream is not None:
            self.stream.write(pcm)

    def finish(self) -> float:
        """受信した音声の秒数を返し、必要なら保存する。"""
        if not self.buf:
            return 0.0
        all_pcm = np.concatenate(self.buf)
        secs = len(all_pcm) / self.rate
        if self.save is not None:
            with wave.open(str(self.save), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(self.rate)
                w.writeframes(all_pcm.tobytes())
            print(f"  [保存] {self.save} ({secs:.2f}s)")
        self.buf.clear()
        return secs


async def run(args) -> int:
    url = f"ws://{args.host}:{args.port}{args.path}"
    core = DummyCore(play=not args.no_play, save=Path(args.save) if args.save else None)

    print(f"[接続] {url}")
    try:
        async with websockets.connect(url, max_size=None) as ws:
            print("[接続] 成功")
            await ws.send(json.dumps({"t": "hello", "fw": "dummy-0.1.0"}))

            if args.touch_after:
                asyncio.create_task(_send_touch(ws, args.touch_after))

            deadline = time.monotonic() + args.timeout if args.timeout else None
            while True:
                if deadline is not None:
                    remain = deadline - time.monotonic()
                    if remain <= 0:
                        print("[終了] タイムアウト")
                        break
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=remain)
                    except asyncio.TimeoutError:
                        print("[終了] タイムアウト")
                        break
                else:
                    msg = await ws.recv()

                if isinstance(msg, bytes):
                    core.on_audio(msg)
                    continue

                obj = json.loads(msg)
                t = obj.get("t")
                if t == "state":
                    s, e = obj.get("v", "?"), obj.get("emotion", "?")
                    print(f"  [state] {s:9} / {e:9}  {face(s, e)}")
                elif t == "audio_begin":
                    core.rate = obj.get("rate", 24000)
                    core.received = 0
                    core.begin_at = time.monotonic()
                    core._open_stream()
                    print(f"  [audio] begin {core.rate}Hz {obj.get('fmt')}")
                elif t == "audio_end":
                    secs = core.finish()
                    el = time.monotonic() - core.begin_at
                    print(f"  [audio] end   {core.received} bytes / 音声 {secs:.2f}s / 経過 {el:.2f}s")
                    core._close_stream()
                    await ws.send(json.dumps({"t": "audio_done"}))
                elif t == "audio_flush":
                    core.buf.clear()
                    core.received = 0
                    print("  [audio] flush（barge-in）")
                    core._close_stream()
                else:
                    print(f"  [その他] {obj}")
    except OSError as e:
        print(f"[失敗] 接続できません: {e}")
        print("  PC 側が --serve 付きで起動しているか確認してください。")
        return 1
    except websockets.ConnectionClosed:
        print("[終了] サーバから切断されました")
    finally:
        core._close_stream()
    return 0


async def _send_touch(ws, delay: float) -> None:
    await asyncio.sleep(delay)
    print(f"  [送信] touch")
    await ws.send(json.dumps({"t": "touch", "x": 160, "y": 120}))


def main() -> int:
    ap = argparse.ArgumentParser(description="CoreS3 の代わりをするダミークライアント")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--path", default="/rabbit")
    ap.add_argument("--no-play", action="store_true", help="音を鳴らさない")
    ap.add_argument("--save", help="受信した音声を WAV に保存する")
    ap.add_argument("--touch-after", type=float, help="この秒数後に touch を送る")
    ap.add_argument("--timeout", type=float, help="この秒数で終了する")
    args = ap.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
