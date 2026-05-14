import json
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from src.automation.tools.google_form_tools import (
    GoogleFormInspectorTool,
    GoogleFormSubmitTool,
    _extract_form_id,
    _parse_questions,
)

FORM_ID = "1FAIpQLSc0E2-jTMy8WNFLlHc5rG4zw3U1QaCykBra3mdqFv0DNb8i9Q"
FORM_URL = f"https://docs.google.com/forms/d/e/{FORM_ID}/viewform"

# Minimal FB_PUBLIC_LOAD_DATA_ that mirrors the real form structure
FAKE_FORM_DATA = [
    None,
    [
        "企業AI導入資訊",
        [
            [1359586313, "公司名稱",   None, 0, [[383238348, None, 0]], None, None, None, None, None, None, [None, "公司名稱"]],
            [537467526,  "公司規模",   None, 2, [[1779491175, [["0-10",None,None,None,0],["11-100",None,None,None,0],["200 up",None,None,None,0],["",None,None,None,1]], 0]], None, None, None, None, None, None, [None, "公司規模"]],
            [116922308,  "想用AI解決的問題", None, 1, [[687951851, None, 0]], None, None, None, None, None, None, [None, "想用AI解決的問題"]],
        ],
    ],
]
FAKE_HTML = f'<html><script>var FB_PUBLIC_LOAD_DATA_ = {json.dumps(FAKE_FORM_DATA)};\n</script></html>'


def _make_urlopen_mock(body: str, url: str = "https://final.url/formResponse"):
    mock_resp = MagicMock()
    mock_resp.read.return_value = body.encode("utf-8")
    mock_resp.geturl.return_value = url
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ── _parse_questions ──────────────────────────────────────────────────────────

def test_parse_questions_returns_three_questions():
    qs = _parse_questions(FAKE_HTML)
    assert len(qs) == 3


def test_parse_questions_company_name():
    qs = _parse_questions(FAKE_HTML)
    q = next(q for q in qs if "名稱" in q["title"])
    assert q["entry_id"] == "383238348"
    assert q["type"] == "short_answer"


def test_parse_questions_company_size_has_options():
    qs = _parse_questions(FAKE_HTML)
    q = next(q for q in qs if "規模" in q["title"])
    assert q["type"] == "radio"
    assert "0-10" in q["options"]
    assert "11-100" in q["options"]
    assert "200 up" in q["options"]
    # empty "other" sentinel is filtered out
    assert "" not in q["options"]


def test_parse_questions_ai_problem():
    qs = _parse_questions(FAKE_HTML)
    q = next(q for q in qs if "AI" in q["title"])
    assert q["entry_id"] == "687951851"
    assert q["type"] == "paragraph"


def test_parse_questions_raises_on_bad_html():
    with pytest.raises(ValueError, match="FB_PUBLIC_LOAD_DATA_"):
        _parse_questions("<html>no data here</html>")


# ── _extract_form_id ──────────────────────────────────────────────────────────

def test_extract_form_id():
    assert _extract_form_id(FORM_URL) == FORM_ID


# ── GoogleFormInspectorTool ───────────────────────────────────────────────────

def test_inspector_returns_form_id_and_questions():
    with patch("src.automation.tools.google_form_tools.urllib.request.urlopen",
               return_value=_make_urlopen_mock(FAKE_HTML)):
        result = GoogleFormInspectorTool()._run(url=FORM_URL)

    assert result["form_id"] == FORM_ID
    assert len(result["questions"]) == 3


def test_inspector_includes_entry_ids():
    with patch("src.automation.tools.google_form_tools.urllib.request.urlopen",
               return_value=_make_urlopen_mock(FAKE_HTML)):
        result = GoogleFormInspectorTool()._run(url=FORM_URL)

    entry_ids = {q["entry_id"] for q in result["questions"]}
    assert "383238348" in entry_ids
    assert "1779491175" in entry_ids
    assert "687951851" in entry_ids


# ── GoogleFormSubmitTool ──────────────────────────────────────────────────────

def test_submit_returns_submitted_true_on_formResponse_url():
    with patch("src.automation.tools.google_form_tools.urllib.request.urlopen",
               return_value=_make_urlopen_mock("<html>thanks</html>", url="https://g.co/formResponse")):
        result = GoogleFormSubmitTool()._run(
            form_id=FORM_ID,
            responses={"383238348": "Acme", "1779491175": "0-10", "687951851": "triage"},
        )

    assert result["submitted"] is True


def test_submit_uses_other_option_for_其他():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["data"] = req.data.decode("utf-8")
        return _make_urlopen_mock("ok", url="https://g.co/formResponse")

    with patch("src.automation.tools.google_form_tools.urllib.request.urlopen", fake_urlopen):
        GoogleFormSubmitTool()._run(
            form_id=FORM_ID,
            responses={"1779491175": "其他"},
        )

    assert "entry.1779491175=__other_option__" in captured["data"]


def test_submit_posts_correct_entry_ids():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["data"] = req.data.decode("utf-8")
        return _make_urlopen_mock("ok", url="https://g.co/formResponse")

    with patch("src.automation.tools.google_form_tools.urllib.request.urlopen", fake_urlopen):
        GoogleFormSubmitTool()._run(
            form_id=FORM_ID,
            responses={"383238348": "Acme Corp", "1779491175": "11-100", "687951851": "automate"},
        )

    assert "entry.383238348=Acme+Corp" in captured["data"] or "entry.383238348=Acme%20Corp" in captured["data"] or "Acme" in captured["data"]
    assert "11-100" in captured["data"]
