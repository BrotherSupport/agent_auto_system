"""Unit tests for WebScraperFlow — question field removed, url-only interface."""
from unittest.mock import MagicMock

import pytest


# ── Validation ────────────────────────────────────────────────────────────────

def test_raises_on_missing_url():
    from src.automation.flows.web_scraper_flow import WebScraperFlow
    with pytest.raises(Exception):
        WebScraperFlow().kickoff(inputs={"url": ""})


def test_raises_on_no_inputs():
    from src.automation.flows.web_scraper_flow import WebScraperFlow
    with pytest.raises(Exception):
        WebScraperFlow().kickoff(inputs={})


# ── No question field ─────────────────────────────────────────────────────────

def test_state_has_no_question_field():
    from src.automation.flows.web_scraper_flow import WebScraperState
    state = WebScraperState(url="https://example.com", run_id=0)
    assert not hasattr(state, "question"), "question field must be removed from WebScraperState"


# ── Crew interaction ──────────────────────────────────────────────────────────

def test_crew_called_with_url_only(mocker):
    mock_result = MagicMock()
    mock_result.raw = '{"url":"https://example.com","title":"Example","summary":"A test page"}'

    mock_crew_instance = MagicMock()
    mock_crew_instance.crew.return_value.kickoff.return_value = mock_result

    mocker.patch(
        "src.automation.flows.web_scraper_flow.WebScraperCrew",
        return_value=mock_crew_instance,
    )

    from src.automation.flows.web_scraper_flow import WebScraperFlow
    WebScraperFlow().kickoff(inputs={"url": "https://example.com"})

    call_kwargs = mock_crew_instance.crew.return_value.kickoff.call_args
    inputs = call_kwargs.kwargs.get("inputs") or call_kwargs.args[0]
    assert inputs["url"] == "https://example.com"
    assert "question" not in inputs


def test_crew_not_called_with_question_even_if_passed(mocker):
    """Passing a 'question' input should be silently ignored."""
    mock_result = MagicMock()
    mock_result.raw = '{"title":"X","summary":"Y"}'

    mock_crew_instance = MagicMock()
    mock_crew_instance.crew.return_value.kickoff.return_value = mock_result

    mocker.patch(
        "src.automation.flows.web_scraper_flow.WebScraperCrew",
        return_value=mock_crew_instance,
    )

    from src.automation.flows.web_scraper_flow import WebScraperFlow
    WebScraperFlow().kickoff(inputs={"url": "https://example.com", "question": "ignored"})

    call_kwargs = mock_crew_instance.crew.return_value.kickoff.call_args
    inputs = call_kwargs.kwargs.get("inputs") or call_kwargs.args[0]
    assert "question" not in inputs


def test_flow_returns_crew_raw_output(mocker):
    mock_result = MagicMock()
    mock_result.raw = '{"title":"Test","summary":"Content"}'

    mock_crew_instance = MagicMock()
    mock_crew_instance.crew.return_value.kickoff.return_value = mock_result

    mocker.patch(
        "src.automation.flows.web_scraper_flow.WebScraperCrew",
        return_value=mock_crew_instance,
    )

    from src.automation.flows.web_scraper_flow import WebScraperFlow
    result = WebScraperFlow().kickoff(inputs={"url": "https://example.com"})
    assert result is not None
