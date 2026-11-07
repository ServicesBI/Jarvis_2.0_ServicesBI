"""Chamadas HTTP da OpenAI usadas pelos contratos da aplicação FastAPI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_setting


@dataclass(slots=True)
class UpstreamError(Exception):
    status_code: int
    message: str

    def __str__(self) -> str:
        return self.message


class OpenAIGateway:
    """Cliente pequeno e injetavel; nunca devolve ou registra a chave da API."""

    base_url = "https://api.openai.com/v1"

    def __init__(self, *, timeout: float = 45.0) -> None:
        self.timeout = timeout

    @property
    def api_key(self) -> str | None:
        return get_setting("OPENAI_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(
                    method, f"{self.base_url}{path}", headers=self._headers(), **kwargs
                )
            except httpx.HTTPError as exc:
                raise UpstreamError(502, "OpenAI service unavailable") from exc
        if response.is_error:
            try:
                detail = response.json().get("error", {}).get("message")
            except (ValueError, AttributeError):
                detail = None
            raise UpstreamError(response.status_code, detail or "OpenAI request refused")
        return response

    async def create_realtime_session(
        self, *, language: str, voice: str, model: str, instructions: str
    ) -> dict[str, Any]:
        language_code = {"BR": "pt", "ES": "es", "EN": "en"}.get(language, "pt")
        tool = {
            "type": "function",
            "name": "execute_task",
            "description": "Execute an action requested by the user on the computer.",
            "parameters": {
                "type": "object",
                "properties": {"request": {"type": "string"}},
                "required": ["request"],
            },
        }
        payload = {
            "session": {
                "type": "realtime",
                "model": model,
                "instructions": instructions,
                "audio": {
                    "input": {
                        "transcription": {"model": "whisper-1", "language": language_code},
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 500,
                        },
                    },
                    "output": {"voice": voice},
                },
                "tools": [tool],
                "tool_choice": "auto",
            }
        }
        response = await self._request(
            "POST", "/realtime/client_secrets", json=payload
        )
        return response.json()

    async def transcribe(
        self, audio: bytes, *, filename: str, content_type: str, language: str
    ) -> str:
        response = await self._request(
            "POST",
            "/audio/transcriptions",
            data={"model": "whisper-1", "language": language},
            files={"file": (filename, audio, content_type)},
        )
        return str(response.json().get("text", "")).strip()

    async def synthesize(self, *, text: str, voice: str) -> bytes:
        response = await self._request(
            "POST", "/audio/speech", json={"model": "tts-1", "voice": voice, "input": text}
        )
        return response.content

    async def complete(self, *, messages: list[dict[str, Any]], max_tokens: int = 600) -> str:
        response = await self._request(
            "POST",
            "/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
        )
        data = response.json()
        return str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
