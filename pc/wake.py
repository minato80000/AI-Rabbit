"""ウェイクワード判定と会話モードの管理。

専用のウェイクワードモデルは使わない。VAD が切り出した発話を whisper に
かけ、その結果に「うさちゃん」が含まれるかで判定する。日本語がそのまま動き、
ウェイクワードの変更が設定1行で済む。

誤受理が実用上の問題になったら、このモジュールの内部を
openWakeWord などに差し替える（外から見た API は変えない）。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

_SKIP = set(" 　\t\n、。,.!?！？「」『』・…ー-")
_KANJI_EXPANSION = {"兎": "うさぎ", "卯": "う"}


def normalize(text: str) -> tuple[str, list[int]]:
    """照合用に正規化し、正規化後→元テキストの添字対応も返す。

    - カタカナ → ひらがな
    - 記号・空白を除去
    - 一部の漢字を読みに展開
    """
    chars: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        if ch in _SKIP:
            continue
        if ch in _KANJI_EXPANSION:
            for c in _KANJI_EXPANSION[ch]:
                chars.append(c)
                idx.append(i)
            continue
        o = ord(ch)
        if 0x30A1 <= o <= 0x30F6:  # カタカナ → ひらがな
            ch = chr(o - 0x60)
        chars.append(ch.lower())
        idx.append(i)
    return "".join(chars), idx


def _edit_distance(a: str, b: str) -> int:
    """レーベンシュタイン距離。文字列は数文字なので素朴な実装で十分。"""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _fuzzy_find(text: str, word: str, max_dist: int) -> tuple[int, int] | None:
    """text の中から word に近い部分文字列を探し、その範囲を返す。

    whisper は「ウサちゃん」を「おさちゃん」と綴ることがある。
    完全一致だけに頼ると名前を呼んでも反応しないので、少しの誤差を許す。
    """
    n, m = len(text), len(word)
    lo = max(1, m - max_dist)
    hi = m + max_dist
    for start in range(n):
        for length in range(lo, min(hi, n - start) + 1):
            if _edit_distance(text[start:start + length], word) <= max_dist:
                return start, start + length
    return None


@dataclass
class WakeResult:
    addressed: bool  # ウサちゃんに話しかけられたか
    query: str       # ウェイクワードを除いた用件（空なら呼ばれただけ）


class WakeDetector:
    def __init__(
        self,
        words: list[str],
        conversation_window_sec: float = 20.0,
        fuzzy_distance: int = 1,
    ) -> None:
        # 設定側の表記ゆれも吸収するため、単語リストも正規化しておく
        self.words = [normalize(w)[0] for w in words if w.strip()]
        self.window = conversation_window_sec
        self.fuzzy_distance = fuzzy_distance
        self._last_interaction = 0.0
        log.info(
            "wake words: %s (window=%.0fs, fuzzy=%d)",
            self.words, self.window, self.fuzzy_distance,
        )

    @property
    def conversation_active(self) -> bool:
        return (time.monotonic() - self._last_interaction) < self.window

    def touch(self) -> None:
        """会話が成立したので、ウィンドウを延長する。"""
        self._last_interaction = time.monotonic()

    def close(self) -> None:
        self._last_interaction = 0.0

    def check(self, text: str) -> WakeResult:
        if not text:
            return WakeResult(False, "")

        norm, idx = normalize(text)
        for w in self.words:
            pos = norm.find(w)
            if pos >= 0:
                span = (pos, pos + len(w))
            elif self.fuzzy_distance > 0:
                found = _fuzzy_find(norm, w, self.fuzzy_distance)
                if found is None:
                    continue
                span = found
                log.debug("wake word あいまい一致: %r ≒ %r", norm[span[0]:span[1]], w)
            else:
                continue
            # 元テキストから該当スパンを削って用件を取り出す
            start = idx[span[0]]
            end = idx[span[1] - 1] + 1
            query = (text[:start] + text[end:]).strip(" 　、。,.!?！？")
            return WakeResult(True, query)

        # 会話モード中はウェイクワードなしでも受け付ける
        if self.conversation_active:
            return WakeResult(True, text.strip())

        return WakeResult(False, "")
