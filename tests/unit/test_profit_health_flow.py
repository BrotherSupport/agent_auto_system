"""Tests for the profit_health flow's pure file helpers (no LLM)."""
from src.automation.flows import profit_health_flow as flow


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
