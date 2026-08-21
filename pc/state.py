"""対話システムの状態機械。

CoreS3 の顔表示はこの状態に従う（Step 4 で WebSocket 経由で push する）。
Step 1 ではコンソールに出すだけ。
"""
from __future__ import annotations

import enum
from typing import Callable


class State(enum.Enum):
    IDLE = "idle"            # 待機。ウェイクワード待ち
    LISTENING = "listening"  # 発話を拾っている
    THINKING = "thinking"    # STT / LLM 処理中
    SPEAKING = "speaking"    # 喋っている


class Emotion(enum.Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    PUZZLED = "puzzled"
    SURPRISED = "surprised"


# LLM が本文中に埋め込むタグ → Emotion
TAG_TO_EMOTION = {
    "喜": Emotion.HAPPY,
    "困": Emotion.PUZZLED,
    "驚": Emotion.SURPRISED,
    "普": Emotion.NEUTRAL,
}

# 逆引き。会話履歴にタグ付きで残すために使う。
# タグを剥がした文だけを履歴に入れると、モデルが「自分は普段タグを付けない」と
# 学習してしまい、数ターンで付けなくなる。
EMOTION_TO_TAG = {v: k for k, v in TAG_TO_EMOTION.items()}


class StateMachine:
    """状態と感情を持ち、変化したら購読者に通知する。"""

    def __init__(self) -> None:
        self._state = State.IDLE
        self._emotion = Emotion.NEUTRAL
        self._subscribers: list[Callable[[State, Emotion], None]] = []

    def subscribe(self, fn: Callable[[State, Emotion], None]) -> None:
        self._subscribers.append(fn)

    @property
    def state(self) -> State:
        return self._state

    @property
    def emotion(self) -> Emotion:
        return self._emotion

    def set(self, state: State | None = None, emotion: Emotion | None = None) -> None:
        changed = False
        if state is not None and state is not self._state:
            self._state = state
            changed = True
        if emotion is not None and emotion is not self._emotion:
            self._emotion = emotion
            changed = True
        if changed:
            for fn in self._subscribers:
                fn(self._state, self._emotion)
