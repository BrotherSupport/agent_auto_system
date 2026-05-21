import pytest
from unittest.mock import MagicMock


def test_flow_raises_on_empty_fields():
    from src.automation.flows.form_fill_flow import FormFillFlow

    flow = FormFillFlow()
    with pytest.raises(Exception):
        flow.kickoff(inputs={"company_name": "", "company_size": "", "ai_problem": ""})


def test_flow_raises_on_missing_company_name():
    from src.automation.flows.form_fill_flow import FormFillFlow

    flow = FormFillFlow()
    with pytest.raises(Exception):
        flow.kickoff(inputs={"company_name": "", "company_size": "0-10", "ai_problem": "x"})


def test_flow_calls_crew_with_correct_inputs(mocker):
    mock_result = MagicMock()
    mock_result.raw = '{"submitted": true, "confirmation_text": "Thanks"}'

    mock_crew_instance = MagicMock()
    mock_crew_instance.crew.return_value.kickoff.return_value = mock_result

    mocker.patch("src.automation.harness.provider.resolve", return_value=(None, "openai", "gpt-4o-mini"))
    mocker.patch(
        "src.automation.flows.form_fill_flow.FormFillerCrew",
        return_value=mock_crew_instance,
    )

    from src.automation.flows.form_fill_flow import FormFillFlow

    flow = FormFillFlow()
    flow.kickoff(inputs={
        "company_name": "Acme",
        "company_size": "0-10",
        "ai_problem": "triage",
    })

    call_kwargs = mock_crew_instance.crew.return_value.kickoff.call_args
    inputs = call_kwargs.kwargs.get("inputs") or call_kwargs.args[0]
    assert inputs["company_name"] == "Acme"
    assert inputs["company_size"] == "0-10"


def test_flow_returns_crew_result(mocker):
    mock_result = MagicMock()
    mock_result.raw = '{"submitted": true, "confirmation_text": "Done"}'

    mock_crew_instance = MagicMock()
    mock_crew_instance.crew.return_value.kickoff.return_value = mock_result

    mocker.patch("src.automation.harness.provider.resolve", return_value=(None, "openai", "gpt-4o-mini"))
    mocker.patch(
        "src.automation.flows.form_fill_flow.FormFillerCrew",
        return_value=mock_crew_instance,
    )

    from src.automation.flows.form_fill_flow import FormFillFlow

    result = FormFillFlow().kickoff(inputs={
        "company_name": "Corp",
        "company_size": "11-100",
        "ai_problem": "automate",
    })

    assert result is not None
