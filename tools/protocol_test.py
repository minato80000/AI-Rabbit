r"""CoreS3 プロトコルの自己テスト。

サーバとクライアントを同一プロセスで動かし、期待どおりのフレームが
流れるかを確認する。CoreS3 のファームを書く前に、PC 側が仕様どおりに
振る舞うことを保証しておくためのもの。

    .venv\Scripts\python tools\protocol_test.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import numpy as np
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pc.transport.server import RabbitServer  # noqa: E402

PORT = 8799
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(f"  {'OK ' if ok else 'NG '} {label}")


async def collect(ws, seconds: float) -> tuple[list[dict], int]:
    """指定秒数のあいだ受信し、テキストframeの一覧とバイナリ合計バイト数を返す。"""
    texts: list[dict] = []
    nbytes = 0
    try:
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=seconds)
            if isinstance(msg, bytes):
                nbytes += len(msg)
            else:
                texts.append(json.loads(msg))
    except (asyncio.TimeoutError, websockets.ConnectionClosed):
        pass
    return texts, nbytes


def tone(seconds: float, rate: int = 24000) -> np.ndarray:
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    return (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)


async def main() -> int:
    server = RabbitServer(host="127.0.0.1", port=PORT)
    events: list[dict] = []
    server.on_event(events.append)
    await server.start()
    url = f"ws://127.0.0.1:{PORT}/rabbit"

    print("=== 1. 接続と hello ===")
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"t": "hello", "fw": "test"}))
        await asyncio.sleep(0.2)
        check(server.clients == 1, "サーバがクライアントを1台認識している")
        check(any(e.get("t") == "hello" for e in events), "hello がイベントとして届く")

        print("=== 2. 状態の push ===")
        server.push_state("thinking", "neutral")
        server.push_state("speaking", "happy")
        texts, _ = await collect(ws, 0.4)
        states = [t for t in texts if t.get("t") == "state"]
        check(len(states) == 2, f"state が2件届く（実際 {len(states)}件）")
        check(states and states[-1] == {"t": "state", "v": "speaking", "emotion": "happy"},
              "最後の state の中身が正しい")

        print("=== 3. 音声の転送 ===")
        pcm = tone(0.5)
        server.enqueue(pcm)
        await server.drain()
        texts, nbytes = await collect(ws, 0.5)
        kinds = [t.get("t") for t in texts]
        check("audio_begin" in kinds, "audio_begin が届く")
        check("audio_end" in kinds, "audio_end が届く")
        expected = len(pcm) * 2
        check(nbytes == expected, f"PCM のバイト数が一致（{nbytes} / 期待 {expected}）")
        begin = next((t for t in texts if t.get("t") == "audio_begin"), {})
        check(begin.get("rate") == 24000 and begin.get("fmt") == "s16le",
              "audio_begin のフォーマット情報が正しい")

        print("=== 4. barge-in（flush） ===")
        server.enqueue(tone(3.0))
        await asyncio.sleep(0.1)
        check(server.busy, "再生中は busy=True")
        server.flush()
        texts, nbytes_after = await collect(ws, 0.4)
        check(any(t.get("t") == "audio_flush" for t in texts), "audio_flush が届く")
        check(not server.busy, "flush 後は busy=False")

        print("=== 5. クライアントからのイベント ===")
        await ws.send(json.dumps({"t": "touch", "x": 10, "y": 20}))
        await ws.send(json.dumps({"t": "imu", "event": "shake"}))
        await asyncio.sleep(0.3)
        check(any(e.get("t") == "touch" for e in events), "touch が届く")
        check(any(e.get("t") == "imu" for e in events), "imu が届く")

    await asyncio.sleep(0.3)
    check(server.clients == 0, "切断が検知される")

    print("=== 6. 再接続と状態の復元 ===")
    server.push_state("idle", "neutral")
    async with websockets.connect(url, max_size=None) as ws2:
        texts, _ = await collect(ws2, 0.4)
        check(any(t.get("t") == "state" and t.get("v") == "idle" for t in texts),
              "接続直後に現在の状態が送られる")

    print("=== 7. 誤ったパスの拒否 ===")
    try:
        async with websockets.connect(f"ws://127.0.0.1:{PORT}/wrong") as ws3:
            await asyncio.wait_for(ws3.recv(), timeout=1.0)
        check(False, "誤パスが拒否される")
    except Exception:
        check(True, "誤パスが拒否される")

    await server.stop()

    ng = [label for ok, label in results if not ok]
    print()
    print(f"=== 結果: {len(results) - len(ng)}/{len(results)} 合格 ===")
    for label in ng:
        print(f"  NG: {label}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
