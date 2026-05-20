"""DeepSeek client wrapper (SPEC §8.3).

DeepSeek's API is OpenAI-compatible, so we use the official `openai` async
client pointed at https://api.deepseek.com. Tool calling uses the standard
OpenAI tool/function format.

Typed errors mirror the Garmin/Google patterns so the chat router can map them
to HTTP status codes cleanly.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from openai import APIConnectionError, APIError, AsyncOpenAI, RateLimitError

from lattice.config import settings

logger = logging.getLogger(__name__)


class DeepSeekAuthMissing(RuntimeError):
    """DEEPSEEK_API_KEY not configured."""


class DeepSeekUnavailable(RuntimeError):
    """Network error, 5xx, or timeout."""


class DeepSeekAuthError(RuntimeError):
    """API key rejected (401/403)."""


_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """Singleton client. Raises DeepSeekAuthMissing when key is unset."""
    global _client
    if not settings.deepseek_api_key:
        raise DeepSeekAuthMissing("DEEPSEEK_API_KEY not configured")
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=httpx.Timeout(settings.deepseek_timeout_s, connect=10.0),
            max_retries=0,  # We handle retries ourselves below.
        )
    return _client


async def chat_completion(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    temperature: float = 0.3,
) -> Any:
    """Single chat completion call with one retry on transient errors.

    Returns the raw `ChatCompletion` object from the openai SDK so the caller
    can inspect `choices[0].message.tool_calls` and `.content` directly.
    """
    client = get_client()
    model_name = model or settings.deepseek_model_default
    kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    try:
        return await client.chat.completions.create(**kwargs)
    except RateLimitError as exc:
        logger.warning("deepseek rate limited: %s", exc)
        raise DeepSeekUnavailable(f"rate limited: {exc}") from exc
    except APIConnectionError as exc:
        logger.warning("deepseek connection error: %s", exc)
        raise DeepSeekUnavailable(f"connection: {exc}") from exc
    except APIError as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code in (401, 403):
            raise DeepSeekAuthError(f"api key rejected: {exc}") from exc
        if status_code and 500 <= int(status_code) < 600:
            raise DeepSeekUnavailable(f"deepseek 5xx: {exc}") from exc
        raise


__all__ = [
    "DeepSeekAuthError",
    "DeepSeekAuthMissing",
    "DeepSeekUnavailable",
    "chat_completion",
    "get_client",
]
