"""PC が繋ぎに行く側になる繋ぎ方（`transport.link` が robot-ap）。

CoreS3 が SoftAP で自分のネットワークを立て、その中で WebSocket サーバに
なる。PC はその WiFi に参加して繋ぎに行く。**ルータもインターネットも
要らない。** どこへ持っていってもロボットの電源を入れれば網ができる。

繋ぎ先は **192.168.4.1 に固定**される。ESP32 の SoftAP がゲートウェイに
必ずこのアドレスを使うため、IP を調べる作業そのものが無くなる
（router / hotspot では PC の IP を調べてファームに書く必要がある）。

代わりに **PC の WiFi はロボットの網に占有される。** この構成では PC が
インターネットに出られない。Ollama / VOICEVOX / whisper はすべてローカルに
あるので対話そのものは動くが、開発中は不便なので、家では hotspot を使い、
持ち出すときだけこちらに切り替えるのがよい。

再接続はこちらから張り直す。ロボットの電源を入れ直しても、PC 側を
起動し直す必要はない。
"""
from __future__ import annotations

import asyncio
import logging

import websockets

from .link import RabbitLink

log = logging.getLogger(__name__)

# 繋がらないときに試し直す間隔。ロボットの起動待ちで何度も出るので短め
RETRY_SEC = 2.0


class RabbitClient(RabbitLink):
    """CoreS3（SoftAP）の WebSocket サーバへ繋ぎに行く。"""

    def __init__(
        self,
        host: str = "192.168.4.1",
        port: int = 8765,
        path: str = "/rabbit",
        sample_rate: int = 24000,
        chunk_ms: int = 20,
    ) -> None:
        super().__init__(sample_rate=sample_rate, chunk_ms=chunk_ms)
        self.host = host
        self.port = port
        self.path = path
        self._task: asyncio.Task | None = None

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}{self.path}"

    def describe(self) -> str:
        return f"{self.url} へ繋ぎに行く（ロボットの WiFi に参加しておくこと）"

    async def start(self) -> None:
        self._start_sender()
        self._task = asyncio.create_task(self._connect_forever())
        log.info("WebSocket クライアント起動: %s", self.url)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        await super().stop()

    async def _connect_forever(self) -> None:
        """切れたら繋ぎ直す。落ちている間もアプリ側は止めない。"""
        complained = False
        while True:
            try:
                # PCM は圧縮しても縮まないので permessage-deflate は使わない。
                # ファーム側（links2004/WebSockets）も対応していない
                async with websockets.connect(
                    self.url,
                    max_size=None,
                    compression=None,
                    open_timeout=5,
                    ping_interval=15,
                    ping_timeout=10,
                ) as ws:
                    complained = False
                    await self._serve_connection(ws, peer=self.host)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # 起動待ちで延々と出ても仕方がないので、最初の1回だけ出す
                if not complained:
                    complained = True
                    log.info("%s にまだ繋がりません (%s)。繋がるまで試し続けます", self.url, e)
                else:
                    log.debug("再接続に失敗: %s", e)
            await asyncio.sleep(RETRY_SEC)
