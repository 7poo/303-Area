"""Minimal OpenAI-compatible DeepSeek chat-completions adapter."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    """HTTP client with bounded retries and no secret leakage in errors."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_sec: float = 45.0,
        max_retries: int = 2,
    ) -> None:
        # An explicit empty string is an intentional offline/disabled mode;
        # only ``None`` falls back to the process environment.
        self.api_key = os.getenv("DEEPSEEK_API_KEY") if api_key is None else api_key
        self.base_url = (base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.timeout_sec = timeout_sec
        self.max_retries = max(0, min(max_retries, 3))

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise DeepSeekError("DEEPSEEK_API_KEY is not configured")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": max(0.0, min(temperature, 1.0)),
            "max_tokens": max(128, min(max_tokens, 4096)),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                    result = json.loads(response.read().decode("utf-8"))
                choices = result.get("choices") or []
                if not choices or not isinstance(choices[0].get("message"), dict):
                    raise DeepSeekError("DeepSeek response has no assistant message")
                return {
                    "id": result.get("id"),
                    "model": result.get("model", self.model),
                    "usage": result.get("usage"),
                    "message": choices[0]["message"],
                    "finish_reason": choices[0].get("finish_reason"),
                }
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                last_error = DeepSeekError(f"DeepSeek HTTP {exc.code}: {detail}")
                if exc.code < 500 and exc.code != 429:
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
            if attempt < self.max_retries:
                time.sleep(0.5 * (2**attempt))
        raise DeepSeekError(str(last_error or "DeepSeek request failed"))
