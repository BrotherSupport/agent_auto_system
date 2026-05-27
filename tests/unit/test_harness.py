import pytest

# ── validator ─────────────────────────────────────────────────────────────────

def test_validate_google_form_success():
    from src.automation.harness.validator import validate
    vr = validate("google_form_fill", {"submitted": True, "message": "Form submitted successfully today"})
    assert vr.valid


def test_validate_google_form_not_submitted():
    from src.automation.harness.validator import validate
    vr = validate("google_form_fill", {"submitted": False, "message": "Could not submit the form here"})
    assert not vr.valid
    assert "form not submitted" in vr.reason


def test_validate_result_with_error_key():
    from src.automation.harness.validator import validate
    vr = validate("hacker_news_digest", {"error": "something went wrong unexpectedly"})
    assert not vr.valid
    assert "error" in vr.reason


def test_validate_content_too_short():
    from src.automation.harness.validator import validate
    # "True" is 4 chars — below the 20-char threshold
    vr = validate("google_form_fill", {"submitted": True})
    assert not vr.valid
    assert "too short" in vr.reason


def test_validate_unknown_job_type_passes_if_content_ok():
    from src.automation.harness.validator import validate
    vr = validate("unknown_type", {"data": "This is a long enough result content for the check"})
    assert vr.valid


def test_validate_non_dict_result():
    from src.automation.harness.validator import validate
    vr = validate("google_form_fill", "not a dict")
    assert not vr.valid
    assert "not a dict" in vr.reason


def test_validate_hn_digest_success():
    from src.automation.harness.validator import validate
    vr = validate("hacker_news_digest", {
        "stories": ["Top AI news today", "Rust release"],
        "digest": "Here are the highlights from today",
    })
    assert vr.valid


def test_validate_hn_digest_no_stories():
    from src.automation.harness.validator import validate
    vr = validate("hacker_news_digest", {"message": "No results available at this time"})
    assert not vr.valid
    assert "no stories" in vr.reason


def test_validate_x_scraper_success():
    from src.automation.harness.validator import validate
    vr = validate("x_scraper", {"posts": [{"text": "Hello from test account today!"}]})
    assert vr.valid


def test_validate_email_sender_success():
    from src.automation.harness.validator import validate
    vr = validate("email_sender", {"sent": True, "message": "Email delivered to recipient successfully"})
    assert vr.valid


def test_validate_email_sender_not_sent():
    from src.automation.harness.validator import validate
    vr = validate("email_sender", {"sent": False, "reason": "SMTP authentication error occurred"})
    assert not vr.valid
    assert "email not sent" in vr.reason


# ── costs ─────────────────────────────────────────────────────────────────────

def test_estimate_cost_input_tokens():
    from src.automation.harness.costs import estimate_cost
    cost = estimate_cost("gpt-4o-mini", 1_000_000, 0)
    assert abs(cost - 0.15) < 1e-6


def test_estimate_cost_output_tokens():
    from src.automation.harness.costs import estimate_cost
    cost = estimate_cost("gpt-4o-mini", 0, 1_000_000)
    assert abs(cost - 0.60) < 1e-6


def test_estimate_cost_strips_gemini_prefix():
    from src.automation.harness.costs import estimate_cost
    cost_prefixed = estimate_cost("gemini/gemini-2.0-flash", 1_000_000, 0)
    cost_bare = estimate_cost("gemini-2.0-flash", 1_000_000, 0)
    assert cost_prefixed == cost_bare
    assert abs(cost_prefixed - 0.10) < 1e-6


def test_estimate_cost_unknown_model_uses_fallback():
    from src.automation.harness.costs import estimate_cost
    cost = estimate_cost("totally-unknown-model-xyz", 1_000_000, 0)
    assert cost == 1.0  # fallback input rate is 1.0 per 1M tokens


def test_estimate_cost_anthropic_model():
    from src.automation.harness.costs import estimate_cost
    cost = estimate_cost("claude-sonnet-4-6", 1_000_000, 0)
    assert abs(cost - 3.0) < 1e-6


# ── provider ─────────────────────────────────────────────────────────────────

def test_normalize_defaults_to_openai():
    from src.automation.harness.provider import normalize
    provider, model = normalize(None, None)
    assert provider == "openai"
    assert model == "gpt-4o-mini"


def test_normalize_empty_string_defaults_to_openai():
    from src.automation.harness.provider import normalize
    provider, model = normalize("", "")
    assert provider == "openai"
    assert model == "gpt-4o-mini"


def test_normalize_explicit_model():
    from src.automation.harness.provider import normalize
    provider, model = normalize("anthropic", "claude-sonnet-4-6")
    assert provider == "anthropic"
    assert model == "claude-sonnet-4-6"


def test_normalize_default_sentinel_picks_catalog_default():
    from src.automation.harness.provider import normalize
    provider, model = normalize("anthropic", "default")
    assert provider == "anthropic"
    assert model == "claude-haiku-4-5-20251001"


def test_normalize_unknown_provider_falls_back_to_openai_default_model():
    from src.automation.harness.provider import normalize
    provider, model = normalize("totally-unknown", None)
    assert provider == "totally-unknown"
    assert model == "gpt-4o-mini"


def test_resolve_raises_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from src.automation.harness.provider import resolve
    with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
        resolve("openai", "gpt-4o-mini")
