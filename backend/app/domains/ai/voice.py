"""Voice input for the assistant: a finished recording goes to Groq's hosted
Whisper once and the clean text comes back.

The live words a person sees while talking come from the browser's own speech
recognition; this is the quality pass that replaces them when they stop.
Free-tier Groq allows 2,000 requests / 8 audio-hours a day for the whole
portal, and bills every request as at least 10 seconds, so the browser sends
one request per message, never a stream of chunks."""

from __future__ import annotations

import logging

import httpx
from fastapi import HTTPException, status

from app.core.config import settings

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MAX_BYTES = 25 * 1024 * 1024  # Groq free-tier file limit
# Whisper reads the prompt as preceding text: keep it to names it should spell
# right. (A full sentence gets echoed back on silent clips.)
PROMPT = "MindTech Robotics, MTR"
# On silence Whisper tends to echo the prompt back. (Groq's per-segment
# no_speech_prob is always 0, so it can't be used; the browser instead skips
# clips in which the mic never heard voice-level sound.)
ECHOES = {"mindtech robotics", "mtr", "mdr"}


def available() -> bool:
    return bool(settings.groq_api_key)


def transcribe(audio: bytes, filename: str, content_type: str, language: str | None = None) -> str:
    if not available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Voice transcription is not set up (no GROQ_API_KEY)")
    if not audio:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty recording")
    if len(audio) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Recording is over 25 MB")
    data = {"model": settings.ai_transcribe_model, "response_format": "json", "temperature": "0", "prompt": PROMPT}
    if language:
        data["language"] = language
    try:
        res = httpx.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            data=data,
            files={"file": (filename or "speech.webm", audio, content_type or "audio/webm")},
            timeout=60,
        )
    except httpx.HTTPError as exc:
        log.warning("Groq transcription failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Transcription service unreachable") from exc
    if res.status_code == 429:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Voice quota used up for now; your live text was kept")
    if res.status_code >= 400:
        log.warning("Groq transcription %s: %s", res.status_code, res.text[:300])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Transcription failed")
    text = (res.json().get("text") or "").strip()
    return "" if text.strip(" .,!").lower() in ECHOES else text
