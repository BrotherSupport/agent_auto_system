# Cost per 1M tokens (input, output) in USD
_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o-mini":               (0.15,   0.60),
    "gpt-4o":                    (2.50,  10.00),
    # Anthropic
    "claude-haiku-4-5-20251001": (0.25,   1.25),
    "claude-sonnet-4-6":         (3.00,  15.00),
    # Gemini
    "gemini-3.5-flash":          (0.075,  0.30),
    "gemini-3.1-flash-lite":     (0.04,   0.15),
    "gemini-3-flash-preview":    (0.075,  0.30),
    "gemini-2.5-flash":          (0.075,  0.30),
    "gemini-2.0-flash":          (0.10,   0.40),
    "gemini-2.0-flash-lite":     (0.04,   0.15),
    # Legacy (kept for existing run history)
    "gemini-1.5-flash":          (0.075,  0.30),
    "gemini-1.5-pro":            (1.25,   5.00),
}


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    key = model.split("/")[-1]
    rates = _PRICING.get(key, (1.0, 3.0))
    return round((tokens_in * rates[0] + tokens_out * rates[1]) / 1_000_000, 6)
