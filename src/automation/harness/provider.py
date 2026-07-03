import logging
import os

logger = logging.getLogger(__name__)

# Total LLM attempts before giving up (retries on the same model + fallbacks to
# other models in the same provider, combined).
MAX_LLM_ATTEMPTS = 5

# Substrings that mark a transient "model unavailable / overloaded" failure worth
# retrying or falling back from (vs. a hard error like a bad API key or 400).
_RETRIABLE_MARKERS = (
    "503", "unavailable", "overloaded", "high demand", "try again",
    "429", "rate limit", "rate_limit", "resource exhausted", "resourceexhausted",
    "temporarily", "timeout", "timed out", "502", "504",
)


def _is_retriable(exc: Exception) -> bool:
    # Bare TimeoutError/ConnectionError often stringify to "" or to messages that
    # don't contain our markers, so check the type before the substring scan.
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    return any(m in str(exc).lower() for m in _RETRIABLE_MARKERS)

_CATALOG: dict = {
    "openai": {
        "models": ["gpt-4o-mini", "gpt-4o"],
        "default": "gpt-4o-mini",
        "env": "OPENAI_API_KEY",
    },
    "anthropic": {
        "models": ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"],
        "default": "claude-haiku-4-5-20251001",
        "env": "ANTHROPIC_API_KEY",
    },
    "gemini": {
        "models": [
            "gemini/gemini-3.5-flash",
            "gemini/gemini-3.1-flash-lite",
            "gemini/gemini-2.5-pro",
            "gemini/gemini-2.5-flash",
            "gemini/gemini-2.5-flash-lite",
        ],
        "default": "gemini/gemini-2.5-flash",
        "env": "GEMINI_API_KEY",
    },
}

PROVIDER_MODELS: dict[str, list[str]] = {k: v["models"] for k, v in _CATALOG.items()}


def normalize(provider: str | None, model: str | None) -> tuple[str, str]:
    """Return (effective_provider, effective_model) without creating an LLM instance."""
    if not provider:
        provider = "openai"
    cfg = _CATALOG.get(provider, _CATALOG["openai"])
    effective_model = model if model and model != "default" else cfg["default"]
    return provider, effective_model


def fallback_sequence(provider: str | None, model: str | None) -> list[str]:
    """Ordered model attempt sequence for one job: the requested model first,
    then the other models in the SAME provider as fallbacks (de-duped)."""
    effective_provider, effective_model = normalize(provider, model)
    cfg = _CATALOG.get(effective_provider)
    if not cfg:
        # Unknown/custom provider: only try the requested model — never leak
        # another provider's models into the fallback sequence.
        return [effective_model]
    seq: list[str] = []
    for m in (effective_model, *cfg["models"]):
        if m and m not in seq:
            seq.append(m)
    return seq


def has_api_key(provider: str) -> bool:
    """True when an API key is available for ``provider`` (admin-set or env), without
    constructing an LLM or logging. Lets callers skip guaranteed-to-fail providers."""
    cfg = _CATALOG.get(provider)
    if not cfg:
        return False
    from src import settings_store
    return bool(settings_store.get_llm_key(provider, cfg["env"]))


def resolve(provider: str | None, model: str | None, temperature: float = 0.7):
    """Return (llm_instance, effective_provider, effective_model)."""
    from crewai import LLM

    effective_provider, effective_model = normalize(provider, model)
    cfg = _CATALOG.get(effective_provider, _CATALOG["openai"])

    # Prefer an admin-configured key from the DB, falling back to the env var.
    from src import settings_store
    api_key = settings_store.get_llm_key(effective_provider, cfg["env"])
    if api_key:
        # litellm / Gemini code paths read the provider env var directly, so make
        # the resolved key visible to them for this process too.
        os.environ[cfg["env"]] = api_key

    if not api_key:
        logger.error("API key %s not set for provider '%s'", cfg["env"], effective_provider)
        raise OSError(
            f"API key for provider '{effective_provider}' is not set. "
            f"Add {cfg['env']} to your .env file."
        )

    try:
        llm = LLM(model=effective_model, api_key=api_key, temperature=temperature)
    except ImportError as exc:
        raise ImportError(
            f"Provider '{effective_provider}' requires an extra package: {exc}. "
            "Run: uv add 'crewai[google-genai]' (Gemini) or check your install."
        ) from exc

    return llm, effective_provider, effective_model
