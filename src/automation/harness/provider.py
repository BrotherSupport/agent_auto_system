import os

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
            "gemini/gemini-3-flash-preview",
            "gemini/gemini-2.5-flash",
            "gemini/gemini-2.0-flash",
            "gemini/gemini-2.0-flash-lite",
        ],
        "default": "gemini/gemini-2.5-flash",
        "env": "GEMINI_API_KEY",
    },
}

PROVIDER_MODELS: dict[str, list[str]] = {k: v["models"] for k, v in _CATALOG.items()}


def resolve(provider: str | None, model: str | None):
    """Return (llm_instance_or_None, effective_provider, effective_model)."""
    from crewai import LLM

    if not provider:
        provider = "openai"

    cfg = _CATALOG.get(provider, _CATALOG["openai"])
    effective_model = model if model and model != "default" else cfg["default"]
    api_key = os.getenv(cfg["env"])

    if not api_key:
        raise EnvironmentError(
            f"API key for provider '{provider}' is not set. "
            f"Add {cfg['env']} to your .env file."
        )

    try:
        llm = LLM(model=effective_model, api_key=api_key)
    except ImportError as exc:
        raise ImportError(
            f"Provider '{provider}' requires an extra package: {exc}. "
            "Run: uv add 'crewai[google-genai]' (Gemini) or check your install."
        ) from exc

    return llm, provider, effective_model
