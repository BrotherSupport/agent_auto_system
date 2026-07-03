"""Unit tests for the tasker_apply tool's API/DOM helpers (no live calls)."""
from unittest.mock import MagicMock

import src.automation.tools.tasker_apply_tool as T


def _resp(status=200, payload=None):
    r = MagicMock()
    r.status = status
    r.json.return_value = {} if payload is None else payload
    return r


# ── _check (eligibility) ──────────────────────────────────────────────────────

def test_check_eligible(mocker):
    mocker.patch.object(T, "_get_json",
                        return_value={"status": "0", "data": {"can_propose": True}})
    ok, reason = T._check(MagicMock(), "bearer", "TK1")
    assert ok is True and reason == ""


def test_check_cannot_propose(mocker):
    mocker.patch.object(T, "_get_json",
                        return_value={"status": "0", "data": {"can_propose": False}})
    ok, reason = T._check(MagicMock(), "bearer", "TK1")
    assert ok is False and "can_propose=false" in reason


def test_check_maps_known_error_status(mocker):
    mocker.patch.object(T, "_get_json", return_value={"status": "4030213"})
    ok, reason = T._check(MagicMock(), "bearer", "TK1")
    assert ok is False and "own case" in reason


def test_check_unknown_status(mocker):
    mocker.patch.object(T, "_get_json", return_value={"status": "9999999"})
    ok, reason = T._check(MagicMock(), "bearer", "TK1")
    assert ok is False and "9999999" in reason


def test_check_no_response(mocker):
    mocker.patch.object(T, "_get_json", return_value=None)
    ok, reason = T._check(MagicMock(), "bearer", "TK1")
    assert ok is False and "no response" in reason


# ── _case_info (title / content / already-proposed) ───────────────────────────

def test_case_info_nested_data(mocker):
    mocker.patch.object(T, "_get_json", return_value={"status": "0", "data": {
        "title": "T", "content": "C", "budget_text": "$5", "proposal_content": "P"}})
    info = T._case_info(MagicMock(), "bearer", "TK1")
    assert info == {"title": "T", "content": "C", "budget_text": "$5",
                    "proposal_content": "P"}


def test_case_info_flat_payload(mocker):
    mocker.patch.object(T, "_get_json", return_value={"title": "Flat"})
    info = T._case_info(MagicMock(), "bearer", "TK1")
    assert info["title"] == "Flat" and info["proposal_content"] == ""


def test_case_info_minimal_payload(mocker):
    mocker.patch.object(T, "_get_json", return_value={"status": "0"})
    info = T._case_info(MagicMock(), "bearer", "TK1")
    assert info["title"] == "" and info["proposal_content"] == ""


def test_case_info_handles_non_dict_response(mocker):
    # A JSON list / null must not raise AttributeError.
    for bad in ([1, 2, 3], None, "oops"):
        mocker.patch.object(T, "_get_json", return_value=bad)
        info = T._case_info(MagicMock(), "bearer", "TK1")
        assert info["title"] == "" and info["proposal_content"] == ""


# ── _submit (multipart POST) ──────────────────────────────────────────────────

def test_submit_success_sends_expected_multipart():
    ctx = MagicMock()
    ctx.post.return_value = _resp(200, {"status": "0"})
    ok, msg, status = T._submit(ctx, "bearer", "TK1", 1000, 2000, "my proposal")
    assert ok is True and status == "0"
    url = ctx.post.call_args.args[0]
    mp = ctx.post.call_args.kwargs["multipart"]
    assert url == f"{T._API}/api/issue/TK1/proposal"
    assert mp == {"initial_price_min": "1000", "initial_price_max": "2000",
                  "content": "my proposal", "quota_amount": "0"}


def test_submit_maps_known_error():
    ctx = MagicMock()
    ctx.post.return_value = _resp(400, {"status": "2700247"})
    ok, msg, status = T._submit(ctx, "bearer", "TK1", 500, 2000, "c")
    assert ok is False and "min price" in msg and status == "2700247"


def test_submit_maps_quota_exhausted():
    # 2700271 = out of proposal points/quota; it's an account-wide block status.
    ctx = MagicMock()
    ctx.post.return_value = _resp(400, {"status": "2700271"})
    ok, msg, status = T._submit(ctx, "bearer", "TK1", 1000, 2000, "c")
    assert ok is False and status == "2700271"
    assert "quota" in msg.lower() or "點數" in msg
    assert status in T._QUOTA_BLOCK_STATUSES


def test_submit_unknown_status():
    ctx = MagicMock()
    ctx.post.return_value = _resp(400, {"status": "9999999"})
    ok, msg, status = T._submit(ctx, "bearer", "TK1", 1000, 2000, "c")
    assert ok is False and "9999999" in msg


def test_submit_network_exception():
    ctx = MagicMock()
    ctx.post.side_effect = RuntimeError("boom")
    ok, msg, status = T._submit(ctx, "bearer", "TK1", 1000, 2000, "c")
    assert ok is False and "boom" in msg and status is None


def test_submit_non_dict_json_body():
    # resp.json() returning a list must not raise AttributeError.
    ctx = MagicMock()
    ctx.post.return_value = _resp(200, ["unexpected"])
    ok, msg, status = T._submit(ctx, "bearer", "TK1", 1000, 2000, "c")
    assert ok is False  # status missing -> not "0"


def test_submit_never_infers_success_from_http_200_alone():
    # A 200 with a non-JSON body (e.g. an HTML page) must NOT be counted as
    # a recorded proposal — the strict path requires site status "0".
    ctx = MagicMock()
    resp = _resp(200, None)
    resp.json.side_effect = ValueError("not json")
    ctx.post.return_value = resp
    ok, msg, status = T._submit(ctx, "bearer", "TK1", 1000, 2000, "c")
    assert ok is False


# ── _looks_logged_out ─────────────────────────────────────────────────────────

class _FakeLoc:
    def __init__(self, count, visible=True):
        self._count = count
        self._visible = visible

    def count(self):
        return self._count

    @property
    def first(self):
        m = MagicMock()
        m.is_visible.return_value = self._visible
        return m


class _FakePage:
    def __init__(self, url, locators=None):
        self.url = url
        self._locators = locators or {}

    def locator(self, sel):
        return self._locators.get(sel, _FakeLoc(0))


def test_logged_in_when_logout_present():
    page = _FakePage("https://www.tasker.com.tw/cases", {':text("登出")': _FakeLoc(1)})
    assert T._looks_logged_out(page) is False


def test_logged_out_on_auth_url():
    assert T._looks_logged_out(_FakePage("https://www.tasker.com.tw/auth/login")) is True


def test_logged_out_when_only_login_link_visible():
    page = _FakePage("https://www.tasker.com.tw/cases", {
        'a[href*="/auth/login"], a:has-text("立即登入")': _FakeLoc(1, visible=True)})
    assert T._looks_logged_out(page) is True


# ── _collect_page_case_ids (paginated) ────────────────────────────────────────

class _FakeListPage:
    def __init__(self, hrefs):
        self._hrefs = hrefs
        self.mouse = MagicMock()
        self.goto_calls = []

    def goto(self, url, **_kw):
        self.goto_calls.append(url)

    def evaluate(self, _js):
        return self._hrefs

    def wait_for_timeout(self, _ms):
        pass


def test_collect_page_case_ids_dedupes_and_uppercases():
    page = _FakeListPage([
        "/cases/tk111aaa", "/cases/TK111AAA",   # dup (case-insensitive)
        "/cases/TK222BBB", "/other/link", "/cases/TK333CCC",
    ])
    ids = T._collect_page_case_ids(page, "110", 1, lambda m: None)
    assert ids == ["TK111AAA", "TK222BBB", "TK333CCC"]


def test_collect_page_case_ids_requests_the_given_page():
    page = _FakeListPage(["/cases/TK1ABC"])
    T._collect_page_case_ids(page, "110,101", 3, lambda m: None)
    assert page.goto_calls and "page=3" in page.goto_calls[0]
    assert "selected_categories=110,101" in page.goto_calls[0]


# ── run_tasker_apply guard + TaskerApplyTool wrapper ──────────────────────────

def test_run_requires_saved_session(mocker):
    mocker.patch.object(T.os.path, "exists", return_value=False)
    res = T.run_tasker_apply(category_ids="110", min_charge=1000, max_charge=2000)
    assert "error" in res and "session" in res["error"].lower()
    assert res["applied"] == [] and res["skipped"] == []


def test_tool_wrapper_formats_template_and_delegates(mocker):
    captured = {}
    mocker.patch.object(T, "run_tasker_apply",
                        side_effect=lambda **kw: captured.update(kw) or {"applied": []})
    T.TaskerApplyTool()._run(category_ids="110", min_charge=1000, max_charge=2000,
                             proposal_template="Hi {title}", max_cases=3, dry_run=True)
    assert captured["dry_run"] is True and captured["category_ids"] == "110"
    assert captured["proposal_fn"]("MyCase", "desc") == "Hi MyCase"


def test_tool_wrapper_template_without_placeholder(mocker):
    captured = {}
    mocker.patch.object(T, "run_tasker_apply",
                        side_effect=lambda **kw: captured.update(kw) or {"applied": []})
    T.TaskerApplyTool()._run(category_ids="110", min_charge=1000, max_charge=2000,
                             proposal_template="fixed text", dry_run=True)
    assert captured["proposal_fn"]("anything", "d") == "fixed text"


def test_tool_wrapper_catches_exceptions(mocker):
    mocker.patch.object(T, "run_tasker_apply", side_effect=RuntimeError("boom"))
    res = T.TaskerApplyTool()._run(category_ids="110", min_charge=1000, max_charge=2000)
    assert "error" in res and "boom" in res["error"]
