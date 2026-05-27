from unittest.mock import MagicMock

import pytest


def test_x_scraper_flow_raises_on_empty_username():
    from src.automation.flows.x_scraper_flow import XScraperFlow
    with pytest.raises(Exception):
        XScraperFlow().kickoff(inputs={"username": "", "run_id": 0})


def test_x_scraper_flow_raises_on_missing_username():
    from src.automation.flows.x_scraper_flow import XScraperFlow
    with pytest.raises(Exception):
        XScraperFlow().kickoff(inputs={"run_id": 0})


def test_x_scraper_flow_calls_crew_with_correct_username(mocker):
    mock_result = MagicMock()
    mock_result.raw = '{"posts": [{"text": "Hello world post today!", "likes": 10, "retweets": 2}]}'
    mock_result.usage_metrics = None

    mock_crew_instance = MagicMock()
    mock_crew_instance.crew.return_value.kickoff.return_value = mock_result

    mocker.patch("src.automation.harness.provider.resolve", return_value=(None, "openai", "gpt-4o-mini"))
    mocker.patch("src.automation.flows.x_scraper_flow.XScraperCrew", return_value=mock_crew_instance)

    from src.automation.flows.x_scraper_flow import XScraperFlow
    XScraperFlow().kickoff(inputs={"username": "elonmusk", "limit": 3, "run_id": 0})

    call_kwargs = mock_crew_instance.crew.return_value.kickoff.call_args
    inputs = call_kwargs.kwargs.get("inputs") or call_kwargs.args[0]
    assert inputs["username"] == "elonmusk"
    assert inputs["limit"] == 3


def test_x_scraper_flow_returns_crew_result(mocker):
    mock_result = MagicMock()
    mock_result.raw = '{"posts": [{"text": "Test post with enough content here.", "likes": 5}]}'
    mock_result.usage_metrics = None

    mock_crew_instance = MagicMock()
    mock_crew_instance.crew.return_value.kickoff.return_value = mock_result

    mocker.patch("src.automation.harness.provider.resolve", return_value=(None, "openai", "gpt-4o-mini"))
    mocker.patch("src.automation.flows.x_scraper_flow.XScraperCrew", return_value=mock_crew_instance)

    from src.automation.flows.x_scraper_flow import XScraperFlow
    result = XScraperFlow().kickoff(inputs={"username": "paulg", "run_id": 0})
    assert result is not None
