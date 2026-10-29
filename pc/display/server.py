"""会話の表示サーバ。iPad のブラウザに、聞き取った言葉と返事を流す。

    GET /     表示ページ（index.html）
    WS  /ws   会話のイベント（下記）

PC -> ブラウザ（すべて text / JSON）
    {"t":"heard","text":"...","addressed":true|false,"at":<epoch秒>}
        聞き取った言葉。addressed=false は呼びかけと判定されなかったもの
    {"t":"reply","text":"...","emotion":"happy|...","at":<epoch秒>}
        返事の1文。LLM の返事は文単位で何度も届く（喋るのと同じ粒度）
    {"t":"reply_end"}
        1回分の返事の終わり。次の reply は新しい吹き出しになる
    {"t":"state","v":"idle|listening|thinking|speaking","emotion":"..."}
        いまの状態。ページ上部の表示に使う

**CoreS3 の接続（transport）とは別のポートにしてある。** CoreS3 との
WebSocket は繋ぎ方によって PC が待つ側にも繋ぎに行く側にもなるが、
こちらは常に PC が待ち受ける。iPad も同じ WiFi（ホットスポットやロボットの
SoftAP）に参加させれば、どの繋ぎ方でも同じように開ける。

ページを開き直しても話の流れが分かるよう、直近のやりとりを覚えておき、
接続直後にまとめて送る。
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import socket
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any

from websockets.asyncio.server import broadcast, serve

log = logging.getLogger(__name__)

PAGE = Path(__file__).resolve().parent / "index.html"


def local_addresses() -> list[str]:
    """この PC の IPv4 アドレス。iPad で開く URL の案内に使う。

    ループバックは iPad から使えないので除く。取れなければ空。
    """
    addrs: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.add(info[4][0])
    except OSError:
        pass
    return sorted(a for a in addrs if not a.startswith("127."))


class TranscriptDisplay:
    """会話をブラウザに流す。呼ぶ側は待たなくてよい（送信は投げっぱなし）。"""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8780,
        history: int = 50,
        show_unaddressed: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.show_unaddressed = show_unaddressed
        self._clients: set[Any] = set()
        self._server: Any = None
        # 開き直したときに送り直すぶん。state は最新だけでよいので別に持つ
        self._history: collections.deque[dict] = collections.deque(maxlen=max(0, history))
        self._last_state: dict | None = None
        self._page: bytes | None = None

    @property
    def clients(self) -> int:
        return len(self._clients)

    def urls(self) -> list[str]:
        if self.host not in ("0.0.0.0", "", "::"):
            return [f"http://{self.host}:{self.port}/"]
        return [f"http://{a}:{self.port}/" for a in local_addresses()]

    # --- 待ち受け --------------------------------------------------------
    async def start(self) -> None:
        self._page = PAGE.read_bytes()
        self._server = await serve(
            self._handle, self.host, self.port,
            process_request=self._process_request,
        )
        log.info("表示サーバ起動: http://%s:%d/", self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    def _process_request(self, connection, request):
        """WebSocket 以外の要求をさばく。None を返すとハンドシェイクに進む。"""
        path = request.path.split("?", 1)[0]
        if path == "/ws":
            return None
        if path in ("/", "/index.html"):
            response = connection.respond(HTTPStatus.OK, "")
            response.body = self._page or b""
            del response.headers["Content-Type"]
            del response.headers["Content-Length"]
            response.headers["Content-Type"] = "text/html; charset=utf-8"
            response.headers["Content-Length"] = str(len(response.body))
            response.headers["Cache-Control"] = "no-store"
            return response
        return connection.respond(HTTPStatus.NOT_FOUND, "Not Found\n")

    async def _handle(self, ws) -> None:
        # 開き直したときに話の流れが分かるよう、覚えているぶんを先に送る
        backlog = list(self._history)
        if self._last_state is not None:
            backlog.append(self._last_state)
        try:
            for msg in backlog:
                await ws.send(json.dumps(msg, ensure_ascii=False))
        except Exception:
            return

        self._clients.add(ws)
        log.info("表示端末 接続: %s (計 %d 台)", ws.remote_address, len(self._clients))
        try:
            # 送るだけで、ブラウザからは何も受け取らない
            async for _ in ws:
                pass
        except Exception:
            pass
        finally:
            self._clients.discard(ws)
            log.info("表示端末 切断: %s (残り %d 台)", ws.remote_address, len(self._clients))

    # --- 送信 -----------------------------------------------------------
    def _send(self, msg: dict, keep: bool = True) -> None:
        if keep:
            self._history.append(msg)
        if self._clients:
            # broadcast は待たない。遅い端末があっても対話ループは止めない
            broadcast(self._clients, json.dumps(msg, ensure_ascii=False))

    def heard(self, text: str, addressed: bool) -> None:
        if not addressed and not self.show_unaddressed:
            return
        self._send({"t": "heard", "text": text, "addressed": bool(addressed),
                    "at": round(time.time(), 3)})

    def reply(self, text: str, emotion: str) -> None:
        self._send({"t": "reply", "text": text, "emotion": emotion,
                    "at": round(time.time(), 3)})

    def reply_end(self) -> None:
        self._send({"t": "reply_end"})

    def push_state(self, state: str, emotion: str) -> None:
        msg = {"t": "state", "v": state, "emotion": emotion}
        self._last_state = msg
        self._send(msg, keep=False)


async def _demo(port: int) -> None:
    """ロボットなしでページの見た目を確かめる。"""
    disp = TranscriptDisplay(port=port)
    await disp.start()
    for url in disp.urls() or [f"http://127.0.0.1:{port}/"]:
        print(f"  {url}")
    lines = [
        ("ウサちゃん、今日はいい天気だね", True,
         [("そうなのだ！お散歩日和なのだ。", "happy"), ("どこかへ出かけたいのだ。", "happy")]),
        ("テレビの音", False, []),
        ("明日の天気はどうかな", True,
         [("うーん、ボクには天気予報は分からないのだ。", "puzzled")]),
    ]
    while True:
        for heard, addressed, replies in lines:
            disp.push_state("thinking", "neutral")
            await asyncio.sleep(0.8)
            disp.heard(heard, addressed)
            for text, emo in replies:
                disp.push_state("speaking", emo)
                disp.reply(text, emo)
                await asyncio.sleep(1.5)
            if replies:
                disp.reply_end()
            disp.push_state("idle", "neutral")
            await asyncio.sleep(2.5)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="表示ページをダミーの会話で試す")
    ap.add_argument("--port", type=int, default=8780)
    try:
        asyncio.run(_demo(ap.parse_args().port))
    except KeyboardInterrupt:
        pass
