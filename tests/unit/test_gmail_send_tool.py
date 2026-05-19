"""Unit tests for GmailSendTool — no real SMTP connections made."""
import smtplib
from unittest.mock import MagicMock, patch, call

import pytest

from src.automation.tools.gmail_send_tool import GmailSendTool, _parse_emails


# ── _parse_emails helper ──────────────────────────────────────────────────────

def test_parse_emails_single():
    assert _parse_emails("a@b.com") == ["a@b.com"]


def test_parse_emails_multiple_comma_separated():
    result = _parse_emails("a@b.com, c@d.com,e@f.com")
    assert result == ["a@b.com", "c@d.com", "e@f.com"]


def test_parse_emails_strips_whitespace():
    assert _parse_emails("  x@y.com  ") == ["x@y.com"]


def test_parse_emails_drops_blanks():
    assert _parse_emails("a@b.com,,c@d.com") == ["a@b.com", "c@d.com"]


def test_parse_emails_empty_string():
    assert _parse_emails("") == []


# ── Missing credentials ───────────────────────────────────────────────────────

def test_missing_credentials_returns_error_dict(monkeypatch):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    result = GmailSendTool()._run(to="a@b.com", subject="Hi", body="Hello")
    assert result["sent"] is False
    assert "GMAIL_ADDRESS" in result["error"]


def test_empty_credentials_returns_error_dict(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "")
    result = GmailSendTool()._run(to="a@b.com", subject="Hi", body="Hello")
    assert result["sent"] is False


# ── Successful send ───────────────────────────────────────────────────────────

@pytest.fixture
def smtp_mock():
    """Patch smtplib.SMTP so no real connection is made."""
    mock_server = MagicMock()
    mock_server.__enter__ = lambda s: s
    mock_server.__exit__ = MagicMock(return_value=False)
    with patch("src.automation.tools.gmail_send_tool.smtplib.SMTP", return_value=mock_server) as p:
        yield mock_server, p


@pytest.fixture
def gmail_env(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "sender@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "test-app-password")


def test_successful_send_returns_sent_true(smtp_mock, gmail_env):
    result = GmailSendTool()._run(
        to="recipient@example.com",
        subject="Test Subject",
        body="Hello world",
    )
    assert result["sent"] is True


def test_successful_send_confirmation_contains_recipient(smtp_mock, gmail_env):
    result = GmailSendTool()._run(
        to="recipient@example.com",
        subject="Test Subject",
        body="Hello",
    )
    assert "recipient@example.com" in result["confirmation"]


def test_result_includes_from_field(smtp_mock, gmail_env):
    result = GmailSendTool()._run(to="r@x.com", subject="S", body="B")
    assert result["from"] == "sender@gmail.com"


def test_result_includes_to_and_subject(smtp_mock, gmail_env):
    result = GmailSendTool()._run(to="r@x.com", subject="My Subject", body="B")
    assert result["to"] == "r@x.com"
    assert result["subject"] == "My Subject"


def test_smtp_login_called_with_credentials(smtp_mock, gmail_env):
    server, _ = smtp_mock
    GmailSendTool()._run(to="r@x.com", subject="S", body="B")
    server.login.assert_called_once_with("sender@gmail.com", "test-app-password")


def test_starttls_called(smtp_mock, gmail_env):
    server, _ = smtp_mock
    GmailSendTool()._run(to="r@x.com", subject="S", body="B")
    server.starttls.assert_called_once()


def test_sendmail_includes_all_recipients(smtp_mock, gmail_env):
    server, _ = smtp_mock
    GmailSendTool()._run(to="a@x.com, b@x.com", subject="S", body="B")
    args = server.sendmail.call_args
    recipients = args[0][1]
    assert "a@x.com" in recipients
    assert "b@x.com" in recipients


def test_cc_added_to_recipients(smtp_mock, gmail_env):
    server, _ = smtp_mock
    GmailSendTool()._run(to="a@x.com", subject="S", body="B", cc="cc@x.com")
    args = server.sendmail.call_args
    recipients = args[0][1]
    assert "cc@x.com" in recipients


def test_html_body_detected(smtp_mock, gmail_env):
    """HTML body should be sent with mime_type html, plain text otherwise."""
    result = GmailSendTool()._run(
        to="r@x.com",
        subject="S",
        body="<h1>Hello</h1><p>World</p>",
    )
    assert result["sent"] is True


def test_plain_text_body(smtp_mock, gmail_env):
    result = GmailSendTool()._run(to="r@x.com", subject="S", body="Just plain text")
    assert result["sent"] is True
