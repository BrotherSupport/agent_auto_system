from unittest.mock import MagicMock

import pytest


def test_google_sheet_flow_raises_on_empty_url():
    from src.automation.flows.google_sheet_flow import GoogleSheetFlow
    with pytest.raises(Exception):
        GoogleSheetFlow().kickoff(inputs={"url": "", "run_id": 0})


def test_google_sheet_flow_raises_on_missing_url():
    from src.automation.flows.google_sheet_flow import GoogleSheetFlow
    with pytest.raises(Exception):
        GoogleSheetFlow().kickoff(inputs={"run_id": 0})


def test_google_sheet_flow_calls_crew_with_correct_url(mocker):
    mock_result = MagicMock()
    mock_result.raw = '{"columns": ["id", "name"], "row_count": 2, "summary": "A product list with data", "data": []}'
    mock_result.usage_metrics = None

    mock_crew_instance = MagicMock()
    mock_crew_instance.crew.return_value.kickoff.return_value = mock_result

    mocker.patch("src.automation.harness.provider.resolve", return_value=(None, "openai", "gpt-4o-mini"))
    mocker.patch("src.automation.flows.google_sheet_flow.GoogleSheetCrew", return_value=mock_crew_instance)

    from src.automation.flows.google_sheet_flow import GoogleSheetFlow
    GoogleSheetFlow().kickoff(inputs={
        "url": "https://docs.google.com/spreadsheets/d/abc123/edit",
        "limit": 50,
        "run_id": 0,
    })

    call_kwargs = mock_crew_instance.crew.return_value.kickoff.call_args
    inputs = call_kwargs.kwargs.get("inputs") or call_kwargs.args[0]
    assert inputs["url"] == "https://docs.google.com/spreadsheets/d/abc123/edit"
    assert inputs["limit"] == 50


def test_google_sheet_flow_uses_default_limit(mocker):
    mock_result = MagicMock()
    mock_result.raw = '{"columns": ["col"], "row_count": 1, "summary": "A simple spreadsheet with data", "data": []}'
    mock_result.usage_metrics = None

    mock_crew_instance = MagicMock()
    mock_crew_instance.crew.return_value.kickoff.return_value = mock_result

    mocker.patch("src.automation.harness.provider.resolve", return_value=(None, "openai", "gpt-4o-mini"))
    mocker.patch("src.automation.flows.google_sheet_flow.GoogleSheetCrew", return_value=mock_crew_instance)

    from src.automation.flows.google_sheet_flow import GoogleSheetFlow
    GoogleSheetFlow().kickoff(inputs={
        "url": "https://docs.google.com/spreadsheets/d/abc123/edit",
        "run_id": 0,
    })

    call_kwargs = mock_crew_instance.crew.return_value.kickoff.call_args
    inputs = call_kwargs.kwargs.get("inputs") or call_kwargs.args[0]
    assert inputs["limit"] == 200


def test_google_sheet_flow_returns_crew_result(mocker):
    mock_result = MagicMock()
    mock_result.raw = '{"columns": ["a"], "row_count": 3, "summary": "Sheet with product data", "data": []}'
    mock_result.usage_metrics = None

    mock_crew_instance = MagicMock()
    mock_crew_instance.crew.return_value.kickoff.return_value = mock_result

    mocker.patch("src.automation.harness.provider.resolve", return_value=(None, "openai", "gpt-4o-mini"))
    mocker.patch("src.automation.flows.google_sheet_flow.GoogleSheetCrew", return_value=mock_crew_instance)

    from src.automation.flows.google_sheet_flow import GoogleSheetFlow
    result = GoogleSheetFlow().kickoff(inputs={
        "url": "https://docs.google.com/spreadsheets/d/abc123/edit",
        "run_id": 0,
    })
    assert result is not None
