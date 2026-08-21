"""LLM のストリームを「読み上げ可能な1文」に切り出す。

全文を待たずに1文ずつ TTS へ流すのが、このシステムのレイテンシ設計の要。
ここで同時に、感情タグと thinking ブロックを本文から取り除く。
"""
from __future__ import annotations

import logging
import re

from ..state import TAG_TO_EMOTION, Emotion

log = logging.getLogger(__name__)

_EMOTION_RE = re.compile(r"\[(" + "|".join(TAG_TO_EMOTION) + r")\]")
_SENT_END = "。！？!?"

# 読み上げに乗せると事故る文字。モデルが Markdown や記号を混ぜてくることがある
_TTS_STRIP = re.compile("[" + re.escape("*_`~#|<>[]{}\\") + "]+")
_TTS_SPACE = re.compile(r"\s+")


def sanitize_for_tts(text: str) -> str:
    """TTS に渡す前に読み上げ不能な記号を落とす。"""
    text = _TTS_STRIP.sub("", text)
    # 改行もふくめて空白は1つに畳む。読み上げ文に改行が残ると間が不自然になる
    text = _TTS_SPACE.sub(" ", text)
    return text.strip()
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"

# 1文が長すぎるときに読点で妥協分割する閾値
SOFT_SPLIT_CHARS = 40

# 最初のひと切れだけは、もっと短くても読点で切って先に喋りはじめる。
# VOICEVOX の合成時間は文字数にほぼ比例し（実測 RTF 約 0.5）、
# 2文目以降は前の文の再生中に合成が終わるので、初音出しを決めるのは
# 第1文の長さだけになる。ここを短くするのが体感レイテンシに最も効く。
FIRST_CHUNK_CHARS = 12


def _hold_back(s: str) -> int:
    """末尾が未完成のタグの可能性がある場合、その開始位置を返す。

    デルタの境界で "[喜" や "<thin" のように途中で切れるため、
    閉じ記号が来るまでその手前で処理を止める。
    """
    lookback = max(0, len(s) - 9)
    for i in range(len(s) - 1, lookback - 1, -1):
        if s[i] in "<[":
            closer = ">" if s[i] == "<" else "]"
            if closer not in s[i:]:
                return i
    return len(s)


class SentenceStreamer:
    def __init__(
        self,
        soft_split_chars: int = SOFT_SPLIT_CHARS,
        first_chunk_chars: int = FIRST_CHUNK_CHARS,
    ) -> None:
        self.buf = ""          # まだ処理していない生デルタ
        self.pending = ""      # タグを除去済みで、まだ文として確定していない本文
        self.emotion = Emotion.NEUTRAL
        self.in_think = False
        self.soft_split_chars = soft_split_chars
        self.first_chunk_chars = first_chunk_chars
        self.emitted = 0       # これまでに吐いた切れ数

    def feed(self, delta: str) -> list[tuple[str, Emotion]]:
        self.buf += delta
        cut = _hold_back(self.buf)
        chunk, self.buf = self.buf[:cut], self.buf[cut:]
        if chunk:
            self.pending += self._clean(chunk)
        return self._extract(final=False)

    def flush(self) -> list[tuple[str, Emotion]]:
        if self.buf:
            self.pending += self._clean(self.buf)
            self.buf = ""
        return self._extract(final=True)

    def _clean(self, s: str) -> str:
        """thinking ブロックと感情タグを取り除く。感情は self.emotion に反映。"""
        out: list[str] = []
        while s:
            if self.in_think:
                e = s.find(_THINK_CLOSE)
                if e < 0:
                    s = ""
                    break
                s = s[e + len(_THINK_CLOSE):]
                self.in_think = False
                continue
            b = s.find(_THINK_OPEN)
            if b < 0:
                out.append(s)
                break
            out.append(s[:b])
            s = s[b + len(_THINK_OPEN):]
            self.in_think = True

        text = "".join(out)

        def _take(m: re.Match) -> str:
            self.emotion = TAG_TO_EMOTION[m.group(1)]
            return ""

        return _EMOTION_RE.sub(_take, text)

    def _extract(self, final: bool) -> list[tuple[str, Emotion]]:
        sentences: list[tuple[str, Emotion]] = []

        while True:
            cut = -1
            for i, ch in enumerate(self.pending):
                # 改行はモデルが文の区切りとして使う。句点と同じ扱いにする
                if ch in _SENT_END or ch == "\n":
                    cut = i + 1
                    # 「えっ！？」のように終端が連続する場合はまとめて切る。
                    # 1文字ずつ切ると「？」だけの断片が TTS に流れてしまう
                    while cut < len(self.pending) and (
                        self.pending[cut] in _SENT_END or self.pending[cut] == "\n"
                    ):
                        cut += 1
                    break

            # 終端がバッファ末尾に来た場合、次が「？」かもしれないので1つ待つ。
            # ストリーミングでは「えっ！」の時点で「？」がまだ届いていない
            if cut == len(self.pending) and not final:
                break

            if cut < 0:
                # 句点が来ないまま長くなったら読点で妥協する。
                # 最初のひと切れだけは閾値を下げ、最初の読点で早めに切る。
                if self.emitted == 0:
                    limit = self.first_chunk_chars
                    if len(self.pending) >= limit:
                        comma = self.pending.find("、", 0, limit + 10)
                        if comma > 0:
                            cut = comma + 1
                else:
                    limit = self.soft_split_chars
                    if len(self.pending) >= limit:
                        comma = self.pending.rfind("、", 0, limit + 10)
                        if comma > 0:
                            cut = comma + 1
                if cut < 0:
                    break

            text = sanitize_for_tts(self.pending[:cut])
            self.pending = self.pending[cut:]
            if text:
                sentences.append((text, self.emotion))
                self.emitted += 1

        if final:
            tail = sanitize_for_tts(self.pending)
            self.pending = ""
            if tail:
                sentences.append((tail, self.emotion))
                self.emitted += 1

        return sentences
