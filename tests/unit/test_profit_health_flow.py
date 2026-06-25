"""Tests for the profit_health flow's pure file helpers (no LLM)."""
import json

from src.automation.flows import profit_health_flow as flow
from src.automation.flows.profit_health_flow import ProfitHealthFlow, _parse_report


def test_read_csv_strips_bom(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "UPLOAD_ROOT", tmp_path)
    d = tmp_path / "u1"
    d.mkdir()
    (d / "sales.csv").write_bytes(b"\xef\xbb\xbf" + "商品SKU,數量\nABC,1\n".encode())
    text = flow._read_csv("u1", "sales.csv")
    assert text.startswith("商品SKU")  # BOM removed
    assert "﻿" not in text


def test_read_csv_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "UPLOAD_ROOT", tmp_path)
    (tmp_path / "u2").mkdir()
    assert flow._read_csv("u2", "ads.csv") == ""


def test_truncate_csv_under_limit_unchanged():
    content = "a,b\n1,2\n3,4\n"
    assert flow._truncate_csv(content, max_lines=10) == content


def test_truncate_csv_over_limit():
    content = "\n".join(f"row{i}" for i in range(250))
    out = flow._truncate_csv(content, max_lines=100)
    lines = out.splitlines()
    assert lines[:100] == [f"row{i}" for i in range(100)]
    assert "truncated, 150 more lines" in out


def test_truncate_empty():
    assert flow._truncate_csv("") == ""


def test_parse_report_handles_plain_and_fenced_json():
    assert _parse_report('{"skus": []}') == {"skus": []}
    assert _parse_report('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_report("not json at all") is None
    assert _parse_report('"a string, not an object"') is None  # JSON but not a dict


def test_render_pdf_injects_pdf_url(mocker):
    """render_pdf turns the JSON report into a PDF and adds pdf_url (fail-soft)."""
    rendered = mocker.patch("src.automation.flows.profit_health_flow.render_report_pdf")
    f = ProfitHealthFlow()
    f.state.run_id = 42
    out = f.render_pdf('{"skus": [{"sku": "A"}]}')
    assert rendered.called
    report = json.loads(out)
    assert report["pdf_url"] == "/api/runs/42/report.pdf"


def test_render_pdf_passes_through_non_json():
    f = ProfitHealthFlow()
    f.state.run_id = 1
    raw = "plain text, not a report"
    assert f.render_pdf(raw) == raw


def test_render_pdf_failsoft_when_render_raises(mocker):
    mocker.patch("src.automation.flows.profit_health_flow.render_report_pdf",
                 side_effect=RuntimeError("no chromium"))
    f = ProfitHealthFlow()
    f.state.run_id = 7
    report = json.loads(f.render_pdf('{"skus": []}'))
    assert "pdf_url" not in report          # rendering failed → no link, but report intact
    assert report == {"skus": []}
