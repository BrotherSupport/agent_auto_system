"""POST /api/uploads now accepts all CSVs at once and routes each by filename."""

import pytest

import src.routers.uploads as uploads_mod


@pytest.fixture(autouse=True)
def _tmp_upload_root(tmp_path, mocker):
    mocker.patch.object(uploads_mod, "UPLOAD_ROOT", tmp_path)
    return tmp_path


def _csv(name: str) -> tuple[str, bytes, str]:
    # Header + one row so the file is non-empty.
    return (name, b"col\nval\n", "text/csv")


async def test_classifies_all_files_by_name(client, _tmp_upload_root):
    resp = await client.post("/api/uploads", files=[
        ("files", _csv("shopee_sales_report.csv")),
        ("files", _csv("product_cost.csv")),
        ("files", _csv("ads_discount.csv")),
        ("files", _csv("order_return_refund.csv")),
    ])
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert sorted(data["files"]) == ["ads", "cost", "returns", "sales"]
    assert data["classified"]["sales"] == "shopee_sales_report.csv"
    assert data["classified"]["returns"] == "order_return_refund.csv"

    # Files land under their canonical slot names regardless of upload order.
    dest = _tmp_upload_root / data["upload_id"]
    for fname in ("sales.csv", "cost.csv", "ads.csv", "returns.csv"):
        assert (dest / fname).is_file()


async def test_sales_and_cost_only_is_enough(client):
    resp = await client.post("/api/uploads", files=[
        ("files", _csv("my_sales.csv")),
        ("files", _csv("the_cost_sheet.csv")),
    ])
    assert resp.status_code == 201
    assert sorted(resp.json()["files"]) == ["cost", "sales"]


async def test_missing_required_role_rejected(client):
    # Only an ads file — neither sales nor cost identifiable → 400.
    resp = await client.post("/api/uploads", files=[("files", _csv("ads_only.csv"))])
    assert resp.status_code == 400
    assert "cost" in resp.json()["detail"] and "sales" in resp.json()["detail"]


async def test_unrecognised_file_reported(client):
    resp = await client.post("/api/uploads", files=[
        ("files", _csv("sales.csv")),
        ("files", _csv("cost.csv")),
        ("files", _csv("mystery.csv")),
    ])
    assert resp.status_code == 201
    assert "mystery.csv" in resp.json()["unmatched"]


def test_classify_keywords():
    assert uploads_mod._classify("order_return_refund.csv") == "returns"
    assert uploads_mod._classify("product_cost.csv") == "cost"
    assert uploads_mod._classify("ads_discount.csv") == "ads"
    assert uploads_mod._classify("shopee_sales_report.csv") == "sales"
    assert uploads_mod._classify("廣告報表.csv") == "ads"
    assert uploads_mod._classify("random.csv") is None
