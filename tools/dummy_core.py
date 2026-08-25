r"""CoreS3 の代わりをするダミー。

実機のファームを書く前に、プロトコルと音声転送を検証するための道具。
受け取った音声を PC のスピーカーで鳴らし、状態変化を顔文字で表示する。

    .venv\Scripts\python tools\dummy_core.py
    .venv\Scripts\python tools\dummy_core.py --no-play --save out.wav
    .venv\Scripts\python tools\dummy_core.py --touch-after 5
    .venv\Scripts\python tools\dummy_core.py --mic     マイク入力も代行する

**接続の向きは 2 通りある。** 既定は実機と同じく自分から繋ぎに行く
（transport.link が router / hotspot のとき）。ロボットが親機になる構成
（robot-ap）では実機が待ち受ける側になるので、--serve でその向きを再現する。

    .venv\Scripts\python tools\dummy_core.py --serve

プロトコル自体はどちらでも同じ。詳細は docs/wireless-link.md。
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


class DummyMic:
    """CoreS3 のマイクの代わりに PC のマイクを流す（--mic）。

    実機が無くても PC 側の経路（RemoteMic → VAD → STT）を丸ごと試せる。
    実機と同じ半二重にするため、mic の指示に従うだけでなく、鳴っている
    あいだは自分で閉じる（ファームの mic_in と同じ振る舞い）。
    """

    def __init__(self, ws, loop, frame_samples: int = 512, device=None) -> None:
        self.ws = ws
        self.loop = loop
        self.frame_samples = frame_samples
        self.device = device
        self.rate = 16000
        self.wanted = False
        self.stream = None
        self.task: asyncio.Task | None = None
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
        self.sent = 0

    # --- PC からの指示 ---------------------------------------------------
    def set_wanted(self, on: bool, rate: int) -> None:
        self.wanted = on
        if on:
            self.open(rate)
        else:
            self.close()

    def suspend(self) -> None:
        """鳴っているあいだは閉じる。実機は I2S を明け渡すため。"""
        self.close()

    def resume(self) -> None:
        if self.wanted:
            self.open(self.rate)

    # --- 実際の開閉 -------------------------------------------------------
    def open(self, rate: int) -> None:
        if self.stream is not None and rate == self.rate:
            return
        self.close()
        import sounddevice as sd

        self.rate = rate
        self.stream = sd.InputStream(
            samplerate=rate,
            blocksize=self.frame_samples,
            channels=1,
            dtype="int16",
            device=self.device,
            callback=self._callback,
        )
        self.stream.start()
        self.task = asyncio.create_task(self._sender())
        print(f"  [mic] 開く {rate}Hz")

    def close(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
            print(f"  [mic] 閉じる（送信 {self.sent} bytes）")
            self.sent = 0
        if self.task is not None:
            self.task.cancel()
            self.task = None
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    # --- 受け渡し ---------------------------------------------------------
    def _callback(self, indata, frames, time_info, status) -> None:  # 別スレッド
        # sounddevice はこのバッファを使い回すので必ずコピーする
        data = indata[:, 0].copy().tobytes()
        try:
            self.loop.call_soon_threadsafe(self._put, data)
        except RuntimeError:
            pass  # ループが閉じている

    def _put(self, data: bytes) -> None:
        try:
            self.queue.put_nowait(data)
        except asyncio.QueueFull:
            pass  # 送りきれない分は捨てる（遅延を溜めない）

    async def _sender(self) -> None:
        while True:
            data = await self.queue.get()
            await self.ws.send(data)
            self.sent += len(data)


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


async def session(ws, args) -> None:
    """繋がった1本を、切れるまで実機のように振る舞わせる。

    自分から繋ぎに行ったか、繋がれたかは、ここから先は関係ない。
    実機のファーム（net.cpp）も同じ作りになっている。
    """
    core = DummyCore(play=not args.no_play, save=Path(args.save) if args.save else None)
    mic: DummyMic | None = None
    try:
        hello = {"t": "hello", "fw": "dummy-0.1.0"}
        if args.mic:
            hello["mic"] = True
            mic = DummyMic(ws, asyncio.get_running_loop(),
                           device=args.mic_device)
        await ws.send(json.dumps(hello))

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
            elif t == "mic":
                if mic is None:
                    print(f"  [mic] 指示が来ましたが --mic 無しです: {obj}")
                else:
                    mic.set_wanted(bool(obj.get("on")), int(obj.get("rate", 16000)))
            elif t == "audio_begin":
                # 実機はここで I2S をスピーカーへ明け渡す
                if mic is not None:
                    mic.suspend()
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
                if mic is not None:
                    mic.resume()
            elif t == "audio_flush":
                core.buf.clear()
                core.received = 0
                print("  [audio] flush（barge-in）")
                core._close_stream()
                if mic is not None:
                    mic.resume()
            else:
                print(f"  [その他] {obj}")
    except websockets.ConnectionClosed:
        print("[終了] 相手から切断されました")
    finally:
        core._close_stream()
        if mic is not None:
            mic.close()


async def run_connect(args) -> int:
    """PC が待ち受ける繋ぎ方（transport.link: router / hotspot）の代役。"""
    url = f"ws://{args.host}:{args.port}{args.path}"
    print(f"[接続] {url}")
    try:
        async with websockets.connect(url, max_size=None) as ws:
            print("[接続] 成功")
            await session(ws, args)
    except OSError as e:
        print(f"[失敗] 接続できません: {e}")
        print("  PC 側が起動しているか、transport.link が router / hotspot か確認してください。")
        return 1
    return 0


async def run_serve(args) -> int:
    """ロボットが親機の繋ぎ方（transport.link: robot-ap）の代役。

    実機は SoftAP を立てて自分が WebSocket サーバになる。その向きを
    手元で再現するので、実機なしでも PC 側のクライアント経路を試せる。
    """
    async def handler(ws):
        peer = getattr(ws, "remote_address", None)
        print(f"[接続] PC が繋いできました {peer}")
        await session(ws, args)

    async with websockets.serve(handler, args.bind, args.port, max_size=None):
        print(f"[待受] ws://{args.bind}:{args.port}{args.path}")
        print("  PC 側は transport.link: robot-ap にして起動してください。")
        print(f"  実機ではなく手元で試すなら transport.core_host: \"{args.bind}\"。")
        print("  終了は Ctrl+C。")
        if args.timeout:
            await asyncio.sleep(args.timeout)
            print("[終了] タイムアウト")
        else:
            await asyncio.Future()  # Ctrl+C まで待つ
    return 0


async def run(args) -> int:
    if args.serve:
        return await run_serve(args)
    return await run_connect(args)


async def _send_touch(ws, delay: float) -> None:
    await asyncio.sleep(delay)
    print(f"  [送信] touch")
    await ws.send(json.dumps({"t": "touch", "x": 160, "y": 120}))


def main() -> int:
    ap = argparse.ArgumentParser(description="CoreS3 の代わりをするダミー")
    ap.add_argument("--host", default="127.0.0.1", help="繋ぎに行く先（既定の向き）")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--path", default="/rabbit")
    ap.add_argument("--serve", action="store_true",
                    help="繋ぎに行かず待ち受ける。ロボットが親機の構成"
                         "（transport.link: robot-ap）を実機なしで試すとき")
    ap.add_argument("--bind", default="127.0.0.1", help="--serve で待ち受けるアドレス")
    ap.add_argument("--no-play", action="store_true", help="音を鳴らさない")
    ap.add_argument("--save", help="受信した音声を WAV に保存する")
    ap.add_argument("--touch-after", type=float, help="この秒数後に touch を送る")
    ap.add_argument("--timeout", type=float, help="この秒数で終了する")
    ap.add_argument("--mic", action="store_true",
                    help="PC のマイクを CoreS3 のマイクとして送る（実機なしで PC 側を試す）")
    ap.add_argument("--mic-device", help="--mic で使う入力デバイス")
    args = ap.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
