import pytest


@pytest.mark.e2e
def test_playwright_tool_submits_form():
    """Requires a real browser and live Google Form."""
    from src.automation.tools.playwright_form_tool import PlaywrightFormTool, FORM_URL

    tool = PlaywrightFormTool()
    result = tool._run(
        url=FORM_URL,
        company_name="E2E Test Corp",
        company_size="0-10",
        ai_problem="Automated e2e testing of form submission",
    )
    assert result["submitted"] is True
    assert result["confirmation_text"]


@pytest.mark.e2e
def test_full_flow_runs_successfully():
    """Requires OPENAI_API_KEY and live Google Form."""
    from src.automation.flows.form_fill_flow import FormFillFlow

    flow = FormFillFlow()
    result = flow.kickoff(inputs={
        "company_name": "E2E Test Corp",
        "company_size": "11-100",
        "ai_problem": "Test full CrewAI flow end-to-end",
    })
    assert result is not None
