"""LLM クライアント。

ローカル（Ollama）とクラウド（Claude API）を同じインターフェースで扱う。
設定の llm.backend を切り替えるだけで入れ替わる。
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx

log = logging.getLogger(__name__)


class LLMClient(ABC):
    def __init__(self, system_prompt: str, max_history_turns: int = 8) -> None:
        self.system_prompt = system_prompt
        self.max_history_turns = max_history_turns
        self.history: list[dict[str, str]] = []

    def _trim(self) -> None:
        keep = self.max_history_turns * 2
        if len(self.history) > keep:
            self.history = self.history[-keep:]

    def record(self, user: str, assistant: str) -> None:
        self.history.append({"role": "user", "content": user})
        self.history.append({"role": "assistant", "content": assistant})
        self._trim()

    def reset(self) -> None:
        self.history.clear()

    @abstractmethod
    def stream(self, user_text: str) -> AsyncIterator[str]:
        """テキストのデルタを順に yield する。"""
        ...

    async def aclose(self) -> None:
        pass


class OllamaClient(LLMClient):
    def __init__(
        self,
        system_prompt: str,
        model: str = "qwen3:4b",
        host: str = "http://127.0.0.1:11434",
        max_history_turns: int = 8,
        num_predict: int = 200,
        temperature: float = 0.8,
        num_ctx: int = 2048,
    ) -> None:
        super().__init__(system_prompt, max_history_turns)
        self.model = model
        self.host = host.rstrip("/")
        self.num_predict = num_predict
        self.temperature = temperature
        self.num_ctx = num_ctx
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0))

    async def health(self) -> str:
        """疎通確認。モデルが未取得ならその旨を返す。"""
        r = await self._client.get(f"{self.host}/api/tags")
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
        if not any(n == self.model or n.startswith(self.model + ":") for n in names):
            raise RuntimeError(
                f"Ollama にモデル {self.model} がありません。"
                f"`ollama pull {self.model}` を実行してください。(現在: {names})"
            )
        return self.model

    async def stream(self, user_text: str) -> AsyncIterator[str]:
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_text})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            # Qwen3 系は推論モードを持つ。対話ロボットでは遅延に直結するので切る
            "think": False,
            "options": {
                "num_predict": self.num_predict,
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
            },
        }

        async with self._client.stream("POST", f"{self.host}/api/chat", json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    log.debug("non-JSON line from ollama: %r", line[:200])
                    continue
                if err := obj.get("error"):
                    raise RuntimeError(f"Ollama error: {err}")
                delta = obj.get("message", {}).get("content", "")
                if delta:
                    yield delta
                if obj.get("done"):
                    break

    async def aclose(self) -> None:
        await self._client.aclose()


class ClaudeClient(LLMClient):
    """Claude API 版。llm.backend: claude で使う。ANTHROPIC_API_KEY が必要。

    ペルソナは system に置いて prompt caching を効かせる。会話用途なので
    effort は low（thinking は切らない。切ると本文が乱れる既知の挙動がある）。
    """

    def __init__(
        self,
        system_prompt: str,
        model: str = "claude-opus-5",
        max_history_turns: int = 8,
        max_tokens: int = 1024,
    ) -> None:
        super().__init__(system_prompt, max_history_turns)
        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:
            raise RuntimeError(
                "Claude バックエンドには anthropic パッケージが必要です: pip install anthropic"
            ) from e
        if not os.environ.get("ANTHROPIC_API_KEY"):
            log.warning("ANTHROPIC_API_KEY が未設定です")
        self.model = model
        self.max_tokens = max_tokens
        self._client = AsyncAnthropic()

    async def health(self) -> str:
        return self.model

    async def stream(self, user_text: str) -> AsyncIterator[str]:
        messages = list(self.history)
        messages.append({"role": "user", "content": user_text})

        async with self._client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[
                {
                    "type": "text",
                    "text": self.system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
        ) as s:
            async for text in s.text_stream:
                yield text

    async def aclose(self) -> None:
        await self._client.close()


def build(cfg: dict, system_prompt: str) -> LLMClient:
    backend = cfg.get("backend", "ollama")
    if backend == "ollama":
        return OllamaClient(
            system_prompt,
            model=cfg.get("model", "qwen3:4b"),
            host=cfg.get("host", "http://127.0.0.1:11434"),
            max_history_turns=cfg.get("max_history_turns", 8),
            num_predict=cfg.get("num_predict", 200),
            temperature=cfg.get("temperature", 0.8),
            num_ctx=cfg.get("num_ctx", 2048),
        )
    if backend == "claude":
        return ClaudeClient(
            system_prompt,
            model=cfg.get("claude_model", "claude-opus-5"),
            max_history_turns=cfg.get("max_history_turns", 8),
        )
    raise ValueError(f"unknown llm.backend: {backend}")
