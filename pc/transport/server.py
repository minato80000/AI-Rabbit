"""CoreS3 との WebSocket 接続。

CoreS3 がクライアントとして接続してくる（PC 側の IP を固定するだけで済み、
CoreS3 の IP を知る必要がない）。

PC -> CoreS3
    text   {"t":"state","v":"idle|listening|thinking|speaking","emotion":"..."}
    text   {"t":"audio_begin","rate":24000,"ch":1,"fmt":"s16le"}
    binary PCM チャンク（20ms 単位）
    text   {"t":"audio_end"}
    text   {"t":"audio_flush"}   barge-in。バッファ即破棄

CoreS3 -> PC
    text   {"t":"hello","fw":"0.1.0"}
    text   {"t":"touch","x":..,"y":..}
    text   {"t":"imu","event":"lift|shake|pat"}
    text   {"t":"audio_done"}    再生し終わった（任意。無くても推定で動く）
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

import numpy as np
import websockets

log = logging.getLogger(__name__)

PREBUFFER_MS = 100


class RabbitServer:
    """音声の出力先であり、状態の通知先であり、センサ入力の受け口。

    AudioSink プロトコルを満たすので Player と差し替えられる。
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        path: str = "/rabbit",
        sample_rate: int = 24000,
        chunk_ms: int = 20,
    ) -> None:
        self.host = host
        self.port = port
        self.path = path
        self.sample_rate = sample_rate
        self.chunk_samples = max(1, int(sample_rate * chunk_ms / 1000))

        self._clients: set[Any] = set()
        self._server: Any = None
        self._outq: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self._sender_task: asyncio.Task | None = None
        self._event_cb: Callable[[dict], None] | None = None

        # 再生終了の推定。CoreS3 から audio_done が来ればそれで上書きする
        self._play_until = 0.0
        self._streaming = False
        self._done_event = asyncio.Event()
        self._done_event.set()
        self._last_state: dict | None = None

    # --- サーバ ---------------------------------------------------------
    async def start(self) -> None:
        self._server = await websockets.serve(self._handle, self.host, self.port)
        self._sender_task = asyncio.create_task(self._sender())
        log.info("WebSocket サーバ起動: ws://%s:%d%s", self.host, self.port, self.path)

    async def stop(self) -> None:
        if self._sender_task is not None:
            self._sender_task.cancel()
            self._sender_task = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    def on_event(self, cb: Callable[[dict], None]) -> None:
        self._event_cb = cb

    @property
    def clients(self) -> int:
        return len(self._clients)

    async def _handle(self, ws) -> None:
        req_path = getattr(getattr(ws, "request", None), "path", self.path)
        if req_path != self.path:
            log.warning("想定外のパスで接続: %s", req_path)
            await ws.close(code=1008, reason="unexpected path")
            return

        peer = getattr(ws, "remote_address", None)
        self._clients.add(ws)
        log.info("CoreS3 接続: %s (計 %d 台)", peer, len(self._clients))

        # 接続直後に現在の状態を送って顔を合わせる
        if self._last_state is not None:
            try:
                await ws.send(json.dumps(self._last_state, ensure_ascii=False))
            except Exception:
                pass

        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    log.debug("クライアントからのバイナリは未使用 (%d bytes)", len(msg))
                    continue
                self._on_message(msg)
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)
            log.info("CoreS3 切断: %s (残り %d 台)", peer, len(self._clients))

    def _on_message(self, raw: str) -> None:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("JSON として読めないメッセージ: %r", raw[:200])
            return
        kind = obj.get("t")
        if kind == "audio_done":
            self._play_until = 0.0
            self._done_event.set()
        if self._event_cb is not None:
            self._event_cb(obj)

    # --- 送信 -----------------------------------------------------------
    async def _sender(self) -> None:
        """送信は1本のタスクに集約する。順序が崩れると音が飛ぶため。"""
        while True:
            kind, payload = await self._outq.get()
            if not self._clients:
                continue
            data = payload if kind == "bin" else json.dumps(payload, ensure_ascii=False)
            dead = []
            for ws in list(self._clients):
                try:
                    await ws.send(data)
                except Exception as e:
                    log.debug("送信失敗、切断扱いにします: %s", e)
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)

    def _put(self, kind: str, payload: Any) -> None:
        try:
            self._outq.put_nowait((kind, payload))
        except asyncio.QueueFull:
            log.warning("送信キューが詰まっています")

    # --- 状態の通知 -----------------------------------------------------
    def push_state(self, state: str, emotion: str) -> None:
        msg = {"t": "state", "v": state, "emotion": emotion}
        self._last_state = msg
        self._put("text", msg)

    # --- AudioSink -------------------------------------------------------
    def enqueue(self, pcm: np.ndarray) -> None:
        if pcm.dtype != np.int16:
            pcm = pcm.astype(np.int16)

        if not self._streaming:
            self._streaming = True
            self._done_event.clear()
            self._put("text", {
                "t": "audio_begin",
                "rate": self.sample_rate,
                "ch": 1,
                "fmt": "s16le",
            })
            # 送り始めてからプリバッファ分だけ遅れて鳴り始める
            self._play_until = time.monotonic() + PREBUFFER_MS / 1000.0

        duration = len(pcm) / self.sample_rate
        now = time.monotonic()
        self._play_until = max(self._play_until, now) + duration

        for i in range(0, len(pcm), self.chunk_samples):
            self._put("bin", pcm[i : i + self.chunk_samples].tobytes())

    def flush(self) -> None:
        # 積んである未送信分を捨ててから flush を送る
        while True:
            try:
                self._outq.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._streaming = False
        self._play_until = 0.0
        self._put("text", {"t": "audio_flush"})
        self._done_event.set()

    @property
    def busy(self) -> bool:
        if not self._clients:
            return False
        return time.monotonic() < self._play_until

    async def drain(self) -> None:
        """鳴らし終わるまで待つ。

        CoreS3 から audio_done が来ればそれを使い、来なければ送った音声の
        長さから推定する（ファームが未実装でも動くようにするため）。
        """
        while self.busy:
            await asyncio.sleep(0.02)
        if self._streaming:
            self._streaming = False
            self._put("text", {"t": "audio_end"})
        self._done_event.set()
