"""Voice input for the assistant: a finished recording goes to Groq's hosted
Whisper once, and the text comes back.

The live words a person sees while talking come from the browser's own speech
recognition; this is the quality pass that replaces them when they stop.
Free-tier Groq allows 2,000 requests / 8 audio-hours a day for the whole
portal, and bills every request as at least 10 seconds, so the browser sends
one request per message, never a stream of chunks.

Members mix Egyptian Arabic and English mid-sentence. Whisper decides one
language per clip, so on its own it drops the other language or spells it in
the wrong script. Two fixes, both checked on mixed test clips:
  1. the prompt is itself mixed text, which tells Whisper mixing is normal;
  2. when the result has Arabic in it, a small text model rewrites English
     words that came out in Arabic letters (سنسر -> sensor). It reuses the
     chat's free model chain and its cooldowns; if none answers, the Whisper
     text is used as is."""

from __future__ import annotations

import logging
import re

import httpx
from fastapi import HTTPException, status

from app.core.config import settings

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MAX_BYTES = 25 * 1024 * 1024  # Groq free-tier file limit
# Whisper reads the prompt as text that came just before the clip.
PROMPT = (
    "MindTech Robotics. OK so we need the servo motors, بس الأول لازم نشوف الـ budget "
    "بتاع الـ drone team. تمام، ابعتلي الـ report والـ task."
)
ARABIC = re.compile(r"[؀-ۿ]")
CLEANUP = (
    "You fix speech-to-text output from members of a robotics team who mix Egyptian Arabic and English. "
    "Rewrite every English word that was written in Arabic letters back in English letters "
    "(e.g. سنسر→sensor, تاسك→task, المانيجر→الـ manager). Keep Arabic words in Arabic script. "
    "Fix only obvious mis-hearings of robotics or team words. Never translate, add, remove or reorder anything else. "
    "Reply with the corrected text only."
)


def available() -> bool:
    return bool(settings.groq_api_key)


def _is_echo(text: str) -> bool:
    """On silence Whisper tends to repeat part of the prompt back. (Groq's
    per-segment no_speech_prob is always 0, so it can't be used; the browser
    also skips clips in which the mic never heard voice-level sound.)"""
    core = text.strip(" .,!،؟?").lower()
    return not core or core in PROMPT.lower() or core in {"mtr", "mdr", "thank you"}


def _cleanup(text: str) -> str:
    if not ARABIC.search(text):
        return text  # pure English: nothing to fix, no request spent
    from app.domains.ai.providers import chain

    for link in chain.parse_chain(settings.ai_transcribe_cleanup):
        key = chain.api_key(link.provider)
        if not key or not chain.available(link) or link.provider not in chain.ENDPOINTS:
            continue
        try:
            res = httpx.post(
                f"{chain.ENDPOINTS[link.provider]}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": link.model, "temperature": 0,
                      "messages": [{"role": "system", "content": CLEANUP}, {"role": "user", "content": text}]},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            log.warning("Voice cleanup via %s failed: %s", link.label, exc)
            continue
        if res.status_code == 429 or res.status_code >= 500:
            chain.cool_down(link, chain.cooldown_for(link, res.status_code, res.headers, res.text))
            continue
        if res.status_code >= 400:
            log.warning("Voice cleanup via %s: %s %s", link.label, res.status_code, res.text[:200])
            continue
        fixed = ((res.json().get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        # A model that rambles or drops half the text is worse than no cleanup.
        if fixed and 0.6 * len(text) <= len(fixed) <= 1.5 * len(text):
            return fixed
        return text
    return text


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
    return "" if _is_echo(text) else _cleanup(text)
