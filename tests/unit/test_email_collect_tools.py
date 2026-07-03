"""Unit tests for the lead-collection funnel tools (no network)."""


# ── web_email_extract: filtering / ranking / guessing ───────────────────────────

def test_junk_emails_filtered():
    from src.automation.tools.email_extract_tool import _is_valid
    assert not _is_valid("a@sentry.io", "acme.com")
    assert not _is_valid("logo@2x.png", "acme.com")
    assert not _is_valid("you@example.com", "acme.com")
    assert not _is_valid("x@sub.wixpress.com", "acme.com")
    assert _is_valid("info@acme.com", "acme.com")


def test_role_addresses_ranked_first():
    from src.automation.tools.email_extract_tool import _rank
    ranked = _rank({"ceo@a.com", "info@a.com", "hello@a.com"})
    assert ranked[0].split("@")[0] in ("info", "hello")
    assert ranked[-1] == "ceo@a.com"


def test_harvest_pulls_mailto_and_text():
    from src.automation.tools.email_extract_tool import _harvest
    html = '<a href="mailto:info@shop.com">mail</a> or reach owner@shop.com today'
    got = _harvest(html)
    assert "info@shop.com" in got
    assert "owner@shop.com" in got


def test_no_guess_on_social_hosts(mocker):
    from src.automation.tools import email_extract_tool as m
    mocker.patch.object(m, "_fetch", return_value="<html>no emails here</html>")
    fb = m.extract_emails("https://www.facebook.com/somebiz/")
    assert fb["emails"] == [] and fb["guessed"] is False


def test_single_role_guess_on_real_domain(mocker):
    from src.automation.tools import email_extract_tool as m
    mocker.patch.object(m, "_fetch", return_value="<html>no emails here</html>")
    r = m.extract_emails("https://acme.com")
    assert r["guessed"] is True
    assert r["emails"] == ["info@acme.com"]


# ── email_verify: layered confidence ────────────────────────────────────────────

def test_verify_rejects_bad_syntax():
    from src.automation.tools.email_verify_tool import verify_email
    r = verify_email("not-an-email", smtp_check=False)
    assert r["syntax_valid"] is False
    assert r["confidence"] == "invalid"


def test_verify_mx_only_role_is_medium(mocker):
    from src.automation.tools import email_verify_tool as m
    mocker.patch.object(m, "_lookup_mx", return_value="mx.acme.com")
    r = m.verify_email("info@acme.com", smtp_check=False)
    assert r["mx_found"] and r["is_role"]
    assert r["confidence"] == "medium"


def test_verify_smtp_accept_is_high(mocker):
    from src.automation.tools import email_verify_tool as m
    mocker.patch.object(m, "_lookup_mx", return_value="mx.acme.com")
    mocker.patch.object(m, "_smtp_probe", return_value="accepted")
    r = m.verify_email("hello@acme.com", smtp_check=True)
    assert r["confidence"] == "high"


def test_verify_no_mx_is_low(mocker):
    from src.automation.tools import email_verify_tool as m
    mocker.patch.object(m, "_lookup_mx", return_value=None)
    r = m.verify_email("info@acme.com", smtp_check=False)
    assert r["mx_found"] is False
    assert r["confidence"] == "low"
