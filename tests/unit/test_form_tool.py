import pytest
from pydantic import ValidationError
from unittest.mock import MagicMock, call

from src.automation.tools.playwright_form_tool import FormInput, PlaywrightFormTool, FORM_URL


@pytest.fixture
def mock_playwright(mocker):
    mock_pw = MagicMock()
    mock_browser = MagicMock()
    mock_page = MagicMock()

    # sync_playwright() is used as a context manager
    mock_pw.__enter__ = MagicMock(return_value=mock_pw)
    mock_pw.__exit__ = MagicMock(return_value=False)
    mock_pw.chromium.launch.return_value = mock_browser
    mock_browser.new_page.return_value = mock_page

    # locator().first / .nth() / .all() chains
    mock_locator = MagicMock()
    mock_locator.first = MagicMock()
    mock_locator.nth = MagicMock(return_value=MagicMock())
    mock_locator.all.return_value = [MagicMock(), MagicMock()]
    mock_locator.count.return_value = 1
    mock_locator.first.text_content.return_value = "感謝您提交表單。"
    mock_page.locator.return_value = mock_locator

    mocker.patch(
        "src.automation.tools.playwright_form_tool.sync_playwright",
        return_value=mock_pw,
    )
    return mock_page


# --- FormInput validation ---

def test_form_input_accepts_valid_size():
    for size in ("0-10", "11-100", "200 up", "其他"):
        fi = FormInput(company_name="Acme", company_size=size, ai_problem="x")
        assert fi.company_size == size


def test_form_input_rejects_invalid_size():
    with pytest.raises(ValidationError):
        FormInput(company_name="Acme", company_size="invalid", ai_problem="x")


def test_form_input_url_defaults_to_form_url():
    fi = FormInput(company_name="A", company_size="0-10", ai_problem="b")
    assert fi.url == FORM_URL


# --- PlaywrightFormTool ---

def test_tool_returns_submitted_true(mock_playwright):
    tool = PlaywrightFormTool()
    result = tool._run(
        url=FORM_URL,
        company_name="Acme",
        company_size="0-10",
        ai_problem="Automate triage",
    )
    assert result["submitted"] is True
    assert "confirmation_text" in result


def test_tool_fills_first_text_input(mock_playwright):
    tool = PlaywrightFormTool()
    tool._run(url=FORM_URL, company_name="Acme Corp", company_size="11-100", ai_problem="x")

    # nth(0).fill("Acme Corp") should have been called
    mock_playwright.locator.return_value.nth.assert_any_call(0)


def test_tool_clicks_radio_for_size(mock_playwright):
    tool = PlaywrightFormTool()
    tool._run(url=FORM_URL, company_name="A", company_size="200 up", ai_problem="x")

    # A locator with the company_size text should have been clicked
    calls = [str(c) for c in mock_playwright.locator.call_args_list]
    assert any("200 up" in c for c in calls)
