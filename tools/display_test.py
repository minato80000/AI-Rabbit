r"""会話の表示サーバ（pc/display）の自己テスト。

サーバとブラウザ役を同一プロセスで動かし、ページが返ることと、
聞き取り・返事・状態が期待どおりに流れることを確認する。

    .venv\Scripts\python tools\display_test.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pc.display import TranscriptDisplay  # noqa: E402

PORT = 8797
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(f"  {'OK ' if ok else 'NG '} {label}")


def http_get(path: str) -> tuple[int, str, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=3) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), ""


async def collect(ws, seconds: float) -> list[dict]:
    out: list[dict] = []
    try:
        while True:
            out.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=seconds)))
    except (asyncio.TimeoutError, websockets.ConnectionClosed):
        pass
    return out


async def main() -> int:
    disp = TranscriptDisplay(host="127.0.0.1", port=PORT, history=4)
    await disp.start()
    url = f"ws://127.0.0.1:{PORT}/ws"

    print("=== 1. ページの配信 ===")
    status, ctype, body = await asyncio.to_thread(http_get, "/")
    check(status == 200, f"/ が 200 を返す（実際 {status}）")
    check(ctype.startswith("text/html"), f"Content-Type が text/html（実際 {ctype!r}）")
    check("<html" in body and "/ws" in body, "中身が表示ページである")
    status, _, _ = await asyncio.to_thread(http_get, "/nothing")
    check(status == 404, f"知らないパスは 404（実際 {status}）")

    print("=== 2. 会話の配信 ===")
    async with websockets.connect(url) as ws:
        await asyncio.sleep(0.2)
        check(disp.clients == 1, "表示端末を1台認識している")
        disp.push_state("thinking", "neutral")
        disp.heard("ウサちゃん、こんにちは", True)
        disp.push_state("speaking", "happy")
        disp.reply("こんにちはなのだ", "happy")
        disp.reply("元気なのだ", "happy")
        disp.reply_end()
        disp.heard("テレビの音", False)
        msgs = await collect(ws, 0.4)
        kinds = [m["t"] for m in msgs]
        check(kinds == ["state", "heard", "state", "reply", "reply", "reply_end", "heard"],
              f"届く順序が正しい（{kinds}）")
        heard = [m for m in msgs if m["t"] == "heard"]
        check(heard and heard[0]["text"] == "ウサちゃん、こんにちは" and heard[0]["addressed"] is True,
              "聞き取った言葉と呼びかけ判定が届く")
        check(len(heard) == 2 and heard[1]["addressed"] is False,
              "呼びかけでない言葉は addressed=false で届く")
        replies = [m for m in msgs if m["t"] == "reply"]
        check([r["text"] for r in replies] == ["こんにちはなのだ", "元気なのだ"]
              and replies[0]["emotion"] == "happy",
              "返事が文単位で感情つきで届く")

    await asyncio.sleep(0.2)
    check(disp.clients == 0, "切断が検知される")

    print("=== 3. 開き直したときの送り直し ===")
    async with websockets.connect(url) as ws:
        msgs = await collect(ws, 0.4)
        kinds = [m["t"] for m in msgs]
        # history=4 なので、覚えている5件のうち最初の heard が落ちる。
        # state は履歴に積まず、最新の1件だけを最後に送る
        check(kinds == ["reply", "reply", "reply_end", "heard", "state"],
              f"直近の履歴と最新の状態が届く（{kinds}）")
        check(msgs and msgs[-1] == {"t": "state", "v": "speaking", "emotion": "happy"},
              "最後に現在の状態が届く")

    print("=== 4. 聞き流した言葉を出さない設定 ===")
    disp.show_unaddressed = False
    async with websockets.connect(url) as ws:
        await collect(ws, 0.3)   # 履歴を読み捨てる
        disp.heard("独り言", False)
        disp.heard("ウサちゃん", True)
        msgs = await collect(ws, 0.3)
        check([m.get("text") for m in msgs] == ["ウサちゃん"], "呼びかけだけが届く")

    await disp.stop()

    ok = sum(1 for r in results if r[0])
    print(f"\n  {ok}/{len(results)} 項目 OK")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
