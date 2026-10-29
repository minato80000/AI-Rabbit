"""ロボットが聞き取った言葉と返事を、iPad などのブラウザに出す。

    from .display import TranscriptDisplay

PC が HTTP と WebSocket を同じポートで待ち受ける。iPad は Safari で
`http://<PC の IP>:8780/` を開くだけでよく、アプリは要らない。
詳細は server.py。
"""
from __future__ import annotations

from .server import TranscriptDisplay, local_addresses

__all__ = ["TranscriptDisplay", "local_addresses"]
