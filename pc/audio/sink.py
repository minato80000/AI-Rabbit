"""音声の出力先。

Step 1 では PC のスピーカー（Player）に流していた。Step 3 で CoreS3 へ
WebSocket 送信するようになるが、開発中は両方に出せたほうが都合がよい
（手元で聞きながらウサギからも出す）。そのための共通インターフェース。
"""
from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class AudioSink(Protocol):
    """int16 mono PCM を受け取って鳴らすもの。"""

    def enqueue(self, pcm: np.ndarray) -> None:
        """再生キューに積む。"""
        ...

    def flush(self) -> None:
        """barge-in。積んだものを破棄して即停止する。"""
        ...

    @property
    def busy(self) -> bool:
        """まだ鳴らし終わっていないか。"""
        ...

    async def drain(self) -> None:
        """鳴らし終わるまで待つ。"""
        ...


class TeeSink:
    """同じ音声を複数の出力先へ流す。

    どれか一つが詰まっても他を止めないよう、例外は握りつぶして記録する。
    CoreS3 が落ちてもローカル再生は続いてほしい。
    """

    def __init__(self, *sinks: AudioSink) -> None:
        self.sinks = [s for s in sinks if s is not None]

    def enqueue(self, pcm: np.ndarray) -> None:
        for s in self.sinks:
            s.enqueue(pcm)

    def flush(self) -> None:
        for s in self.sinks:
            s.flush()

    @property
    def busy(self) -> bool:
        return any(s.busy for s in self.sinks)

    async def drain(self) -> None:
        await asyncio.gather(*(s.drain() for s in self.sinks))


class NullSink:
    """どこにも出さない。CoreS3 だけに出したい場合のローカル側などに使う。"""

    def enqueue(self, pcm: np.ndarray) -> None:
        pass

    def flush(self) -> None:
        pass

    @property
    def busy(self) -> bool:
        return False

    async def drain(self) -> None:
        pass
