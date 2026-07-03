from unittest.mock import MagicMock

import pytest

from src.automation.harness import langfuse_tracer


@pytest.fixture(autouse=True)
def _reset_client():
    # Each test starts with a fresh memoized-client state.
    langfuse_tracer.reset()
    yield
    langfuse_tracer.reset()


def test_is_configured_requires_both_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-x")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert langfuse_tracer.is_configured() is False

    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-x")
    assert langfuse_tracer.is_configured() is True


def test_disabled_flag_overrides_keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-x")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-x")
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    assert langfuse_tracer.is_configured() is False


def test_record_run_noop_when_unconfigured(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    # Returns None and does not raise when Langfuse isn't set up.
    assert langfuse_tracer.record_run(
        run_id=1, job_type="web_scraper", status="success",
        provider="openai", model="gpt-4o-mini",
    ) is None


def test_record_run_emits_trace_and_scores(monkeypatch):
    client = MagicMock()
    client.create_trace_id.return_value = "trace-abc"
    client.get_trace_url.return_value = "https://cloud.langfuse.com/trace/trace-abc"
    root = client.start_observation.return_value
    monkeypatch.setattr(langfuse_tracer, "get_client", lambda: client)

    url = langfuse_tracer.record_run(
        run_id=42, job_type="hacker_news_digest", status="success",
        provider="openai", model="gpt-4o-mini",
        payload={"limit": 5}, result={"digest": "..."},
        tokens_in=100, tokens_out=50, cost_usd=0.001,
        duration_secs=1.23, eval_score=88, eval_confidence=0.9, eval_notes="good",
    )

    assert url == "https://cloud.langfuse.com/trace/trace-abc"
    client.create_trace_id.assert_called_once_with(seed="42")
    # Root span + nested generation created, and the run's IO/scores recorded.
    client.start_observation.assert_called_once()
    root.start_observation.assert_called_once()
    assert root.score_trace.call_count == 2  # eval_score + eval_confidence
    client.flush.assert_called_once()


def test_record_run_swallows_errors(monkeypatch):
    client = MagicMock()
    client.create_trace_id.side_effect = RuntimeError("boom")
    monkeypatch.setattr(langfuse_tracer, "get_client", lambda: client)

    # A tracing failure must never propagate to the caller.
    assert langfuse_tracer.record_run(
        run_id=1, job_type="web_scraper", status="failed",
        provider="openai", model="gpt-4o-mini",
    ) is None
