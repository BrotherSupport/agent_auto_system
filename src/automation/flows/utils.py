def extract_usage(result) -> dict:
    m = getattr(result, "usage_metrics", None)
    if not m:
        return {}
    return {
        "prompt_tokens":     getattr(m, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(m, "completion_tokens", 0) or 0,
    }
