"""PC が待ち受ける側になる繋ぎ方（`transport.link` が router / hotspot）。

CoreS3 がクライアントとして接続してくる。PC 側の IP を固定するだけで済み、
CoreS3 の IP を知る必要がない。

    router   家の WiFi ルータにどちらもぶら下がる。PC の IP は ipconfig で調べる
    hotspot  PC 自身が親機になる（Windows のモバイルホットスポット）。
             ルータが要らず、PC の IP は 192.168.137.1 に固定される

どちらも PC 側の振る舞いは同じなので、この 1 クラスで足りる。
プロトコルと音声の扱いは RabbitLink にある。

**hotspot では Windows ファイアウォールの受信規則が要る。**
新しく生えるネットワークはパブリックに分類され、待ち受けが既定で塞がれる。
`tools\\hotspot.ps1 -Action Firewall`（管理者）で開けられる。
"""
from __future__ import annotations

import logging
from typing import Any

import websockets

from .link import RabbitLink

log = logging.getLogger(__name__)


class RabbitServer(RabbitLink):
    """CoreS3 の接続を待ち受ける。"""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        path: str = "/rabbit",
        sample_rate: int = 24000,
        chunk_ms: int = 20,
    ) -> None:
        super().__init__(sample_rate=sample_rate, chunk_ms=chunk_ms)
        self.host = host
        self.port = port
        self.path = path
        self._server: Any = None

    def describe(self) -> str:
        return f"ws://<このPCのIP>:{self.port}{self.path} で CoreS3 の接続を待つ"

    async def start(self) -> None:
        self._server = await websockets.serve(self._handle, self.host, self.port)
        self._start_sender()
        log.info("WebSocket サーバ起動: ws://%s:%d%s", self.host, self.port, self.path)

    async def stop(self) -> None:
        await super().stop()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, ws) -> None:
        req_path = getattr(getattr(ws, "request", None), "path", self.path)
        if req_path != self.path:
            log.warning("想定外のパスで接続: %s", req_path)
            await ws.close(code=1008, reason="unexpected path")
            return

        await self._serve_connection(ws, peer=getattr(ws, "remote_address", None))
