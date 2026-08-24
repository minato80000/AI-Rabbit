r"""CoreS3 のマイク入力の自己テスト。

サーバと RemoteMic を同一プロセスで動かし、ロボットから届いた PCM が
マイクのフレームとして正しく流れるかを確認する。実機がなくても、
PC 側の経路が仕様どおりかはここで保証できる。

    .venv\Scripts\python tools\core_mic_test.py

出力側は tools の protocol_test.py が見ている。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import numpy as np
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pc.audio.remote_mic import RemoteMic  # noqa: E402
from pc.transport.server import RabbitServer  # noqa: E402

PORT = 8798
RATE = 16000
FRAME = 512

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(f"  {'OK ' if ok else 'NG '} {label}")


async def recv_texts(ws, seconds: float) -> list[dict]:
    out: list[dict] = []
    try:
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=seconds)
            if not isinstance(msg, bytes):
                out.append(json.loads(msg))
    except (asyncio.TimeoutError, websockets.ConnectionClosed):
        pass
    return out


async def drain_frames(mic: RemoteMic) -> list[np.ndarray]:
    await asyncio.sleep(0.05)
    out = []
    while not mic.queue.empty():
        out.append(mic.queue.get_nowait())
    return out


def ramp(n: int, start: int = 0) -> np.ndarray:
    """値の追跡ができるよう、連番を入れた PCM を作る。"""
    return (np.arange(start, start + n, dtype=np.int32) % 3000).astype(np.int16)


async def main() -> int:
    server = RabbitServer(host="127.0.0.1", port=PORT, path="/rabbit")
    await server.start()
    mic = RemoteMic(server, sample_rate=RATE, frame_samples=FRAME)

    url = f"ws://127.0.0.1:{PORT}/rabbit"
    try:
        # --- 1. マイクの開閉指示 ---------------------------------------
        print("=== 1. マイクの開閉指示 ===")
        async with websockets.connect(url, max_size=None) as ws:
            await asyncio.sleep(0.1)
            mic.start()
            texts = await recv_texts(ws, 0.3)
            on = [t for t in texts if t.get("t") == "mic"]
            check(len(on) == 1 and on[0]["on"] is True, "mic on が届く")
            check(bool(on) and on[0].get("rate") == RATE,
                  f"レートが載っている（{on[0].get('rate') if on else None}）")

            mic.paused = True
            texts = await recv_texts(ws, 0.3)
            off = [t for t in texts if t.get("t") == "mic"]
            check(len(off) == 1 and off[0]["on"] is False,
                  "paused にすると mic off が届く（実機の I2S を明け渡す）")

            # --- 2. 閉じている間は積まない -----------------------------
            print("=== 2. 閉じている間 ===")
            await ws.send(ramp(FRAME).tobytes())
            frames = await drain_frames(mic)
            check(len(frames) == 0, "mic off 中に届いた音は捨てられる")

            mic.paused = False
            await recv_texts(ws, 0.2)

            # --- 3. フレームの中身 -------------------------------------
            print("=== 3. フレームの中身 ===")
            pcm = ramp(FRAME)
            await ws.send(pcm.tobytes())
            frames = await drain_frames(mic)
            check(len(frames) == 1, f"1フレーム出てくる（実際 {len(frames)}）")
            if frames:
                f = frames[0]
                check(f.dtype == np.float32 and len(f) == FRAME,
                      f"float32 / {FRAME} サンプル（実際 {f.dtype} / {len(f)}）")
                expect = pcm.astype(np.float32) / 32768.0
                check(bool(np.allclose(f, expect)), "値が s16le として正しく読めている")

            # --- 4. 半端な長さの組み直し -------------------------------
            print("=== 4. 半端な長さで届いた場合 ===")
            big = ramp(FRAME + 100, start=7)
            await ws.send(big[:300].tobytes())
            mid = await drain_frames(mic)
            check(len(mid) == 0, "フレームに満たない分は溜めておく")
            await ws.send(big[300:].tobytes())
            frames = await drain_frames(mic)
            check(len(frames) == 1, f"揃った時点で1フレーム出る（実際 {len(frames)}）")
            if frames:
                expect = big[:FRAME].astype(np.float32) / 32768.0
                check(bool(np.allclose(frames[0], expect)), "またいでも順序と値が保たれる")

            # 3フレームぶんまとめて届いた場合
            many = ramp(FRAME * 3, start=11)
            await ws.send(many.tobytes())
            frames = await drain_frames(mic)
            check(len(frames) == 3, f"まとめて届いても分割される（実際 {len(frames)}）")

            # --- 5. 増幅 -----------------------------------------------
            print("=== 5. 増幅（input_gain）===")
            loud = RemoteMic(server, sample_rate=RATE, frame_samples=FRAME, gain=4.0)
            loud.feed((np.full(FRAME, 8000, dtype=np.int16)).tobytes())
            f = await asyncio.wait_for(loud.queue.get(), timeout=1.0)
            check(abs(float(f[0]) - min(8000 / 32768.0 * 4.0, 1.0)) < 1e-6,
                  "gain が掛かる")
            loud.feed((np.full(FRAME, 30000, dtype=np.int16)).tobytes())
            f = await asyncio.wait_for(loud.queue.get(), timeout=1.0)
            check(float(f.max()) <= 1.0, "増幅しても 1.0 を超えない（クリップする）")

            mic.stop()
            await recv_texts(ws, 0.2)

        # --- 6. 繋がる前の指示 -----------------------------------------
        print("=== 6. 繋がる前に出した指示 ===")
        server.set_mic(True, rate=RATE)
        async with websockets.connect(url, max_size=None) as ws:
            texts = await recv_texts(ws, 0.4)
            got = [t for t in texts if t.get("t") == "mic"]
            check(len(got) == 1 and got[0]["on"] is True,
                  "接続した時点で送り直される")

        # --- 7. 受け口を外したら元どおり -------------------------------
        print("=== 7. 受け口を外したとき ===")
        server.on_audio(None)
        async with websockets.connect(url, max_size=None) as ws:
            await ws.send(ramp(FRAME).tobytes())
            await asyncio.sleep(0.1)
            check(True, "バイナリが来ても落ちない（従来どおり無視）")
    finally:
        await server.stop()

    ok = sum(1 for r, _ in results if r)
    print()
    print(f"=== 結果: {ok}/{len(results)} 合格 ===")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
