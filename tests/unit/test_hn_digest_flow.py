from unittest.mock import MagicMock

import pytest


def test_hn_digest_flow_raises_on_limit_zero():
    from src.automation.flows.hn_digest_flow import HNDigestFlow
    with pytest.raises(Exception):
        HNDigestFlow().kickoff(inputs={"limit": 0, "run_id": 0})


def test_hn_digest_flow_raises_on_limit_over_ten():
    from src.automation.flows.hn_digest_flow import HNDigestFlow
    with pytest.raises(Exception):
        HNDigestFlow().kickoff(inputs={"limit": 11, "run_id": 0})


def test_hn_digest_flow_calls_crew_with_correct_limit(mocker):
    mock_result = MagicMock()
    mock_result.raw = '{"digest": "Top HN stories about AI today", "stories": [1, 2, 3]}'
    mock_result.usage_metrics = None

    mock_crew_instance = MagicMock()
    mock_crew_instance.crew.return_value.kickoff.return_value = mock_result

    mocker.patch("src.automation.harness.provider.resolve", return_value=(None, "openai", "gpt-4o-mini"))
    mocker.patch("src.automation.flows.hn_digest_flow.HNDigestCrew", return_value=mock_crew_instance)

    from src.automation.flows.hn_digest_flow import HNDigestFlow
    HNDigestFlow().kickoff(inputs={"limit": 3, "run_id": 0})

    call_kwargs = mock_crew_instance.crew.return_value.kickoff.call_args
    inputs = call_kwargs.kwargs.get("inputs") or call_kwargs.args[0]
    assert inputs["limit"] == 3


def test_hn_digest_flow_returns_crew_result(mocker):
    mock_result = MagicMock()
    mock_result.raw = '{"digest": "AI and Rust dominate today", "stories": ["story1", "story2"]}'
    mock_result.usage_metrics = None

    mock_crew_instance = MagicMock()
    mock_crew_instance.crew.return_value.kickoff.return_value = mock_result

    mocker.patch("src.automation.harness.provider.resolve", return_value=(None, "openai", "gpt-4o-mini"))
    mocker.patch("src.automation.flows.hn_digest_flow.HNDigestCrew", return_value=mock_crew_instance)

    from src.automation.flows.hn_digest_flow import HNDigestFlow
    result = HNDigestFlow().kickoff(inputs={"limit": 5, "run_id": 0})
    assert result is not None
