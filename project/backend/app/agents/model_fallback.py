"""Shared Gemini model order and retry classification for transient API failures."""

import os


DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_FALLBACK_MODELS = ("gemini-3.8-flash", "gemini-3.6-flash")
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def model_candidates() -> list[str]:
    primary = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    fallbacks = os.getenv(
        "GEMINI_FALLBACK_MODELS",
        ",".join(DEFAULT_FALLBACK_MODELS),
    )
    candidates = [primary]
    candidates.extend(item.strip() for item in fallbacks.split(",") if item.strip())
    return list(dict.fromkeys(candidates))


def is_retryable_error(error: Exception) -> bool:
    """Only retry transient API/network failures; invalid requests/keys fail fast."""
    for attr in ("status_code", "code"):
        status = getattr(error, attr, None)
        try:
            if int(status) in RETRYABLE_STATUS_CODES:
                return True
        except (TypeError, ValueError):
            pass

    name = type(error).__name__.lower()
    message = str(error).lower()
    return (
        isinstance(error, (TimeoutError, ConnectionError))
        or any(token in name for token in ("timeout", "connection"))
        or any(token in message for token in (
            "503", "unavailable", "429", "resource_exhausted",
            "502", "504", "500", "deadline exceeded", "timed out",
        ))
    )
