import json

import pytest

# ── validator ────────────────────────────────────────────────────────────────

def test_validator_accepts_processed_run():
    from src.automation.harness.validator import validate

    result = {"applied": [{"case_id": "TK1"}], "skipped": [], "cases_found": 1,
              "summary": "Category 110: 1 case scanned, 1 prepared, 0 skipped."}
    assert validate("tasker_apply", result).valid


def test_validator_accepts_zero_cases():
    from src.automation.harness.validator import validate

    result = {"applied": [], "skipped": [], "cases_found": 0,
              "summary": "No open cases found for category 110."}
    assert validate("tasker_apply", result).valid


def test_validator_rejects_error():
    from src.automation.harness.validator import validate

    assert not validate("tasker_apply", {"applied": [], "error": "not logged in"}).valid


# ── flow validation ──────────────────────────────────────────────────────────

def test_flow_raises_on_missing_category():
    from src.automation.flows.tasker_apply_flow import TaskerApplyFlow

    flow = TaskerApplyFlow()
    with pytest.raises(Exception):
        flow.kickoff(inputs={"category_ids": "", "min_charge": 100, "max_charge": 200})


def test_flow_raises_when_min_gt_max():
    from src.automation.flows.tasker_apply_flow import TaskerApplyFlow

    flow = TaskerApplyFlow()
    with pytest.raises(Exception):
        flow.kickoff(inputs={"category_ids": "110", "min_charge": 900, "max_charge": 100})


# ── flow orchestration ───────────────────────────────────────────────────────

def test_flow_passes_dry_run_and_returns_json(mocker):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {"category_ids": kwargs["category_ids"], "dry_run": kwargs["dry_run"],
                "applied": [], "skipped": [], "cases_found": 0, "summary": "none"}

    mocker.patch("src.automation.harness.provider.resolve",
                 return_value=(None, "openai", "gpt-4o-mini"))
    mocker.patch("src.automation.flows.tasker_apply_flow.run_tasker_apply",
                 side_effect=fake_run)

    from src.automation.flows.tasker_apply_flow import TaskerApplyFlow

    flow = TaskerApplyFlow()
    raw = flow.kickoff(inputs={
        "category_ids": "110,101001", "min_charge": 5000, "max_charge": 15000,
        "max_cases": 3, "dry_run": False,
    })

    parsed = json.loads(raw if isinstance(raw, str) else raw.raw)
    assert parsed["category_ids"] == "110,101001"
    assert captured["dry_run"] is False
    assert captured["max_cases"] == 3
    assert callable(captured["proposal_fn"])


def test_proposal_fn_falls_back_to_template_without_llm(mocker):
    captured = {}
    mocker.patch("src.automation.flows.tasker_apply_flow.run_tasker_apply",
                 side_effect=lambda **kw: captured.update(kw) or {
                     "applied": [], "skipped": [], "cases_found": 0, "summary": "x"})
    # No LLM available → resolve raises → template-only path.
    mocker.patch("src.automation.harness.provider.resolve",
                 side_effect=OSError("no key"))

    from src.automation.flows.tasker_apply_flow import TaskerApplyFlow

    flow = TaskerApplyFlow()
    flow.kickoff(inputs={
        "category_ids": "110", "min_charge": 1000, "max_charge": 2000,
        "proposal_template": "Hi about {title}",
    })
    text = captured["proposal_fn"]("Build a scraper", "desc")
    assert text == "Hi about Build a scraper"


# ── tool orchestration (mocked API; no live calls) ───────────────────────────

def _mock_playwright(mocker):
    import src.automation.tools.tasker_apply_tool as T
    mocker.patch.object(T.os.path, "exists", return_value=True)
    fake_ctx = mocker.MagicMock()
    fake_pw = mocker.MagicMock()
    fake_pw.chromium.launch.return_value.new_context.return_value = fake_ctx
    cm = mocker.MagicMock()
    cm.__enter__ = lambda s: fake_pw
    cm.__exit__ = lambda *a: False
    mocker.patch("playwright.sync_api.sync_playwright", return_value=cm)
    mocker.patch.object(T, "_capture_session", return_value="Bearer x")
    mocker.patch.object(T, "_collect_case_ids", return_value=["TK1", "TK2"])
    # TK1 is fresh & eligible; TK2 already proposed.
    mocker.patch.object(T, "_case_info", side_effect=lambda req, b, cid: {
        "title": f"case {cid}", "content": "desc", "budget_text": "$1",
        "proposal_content": "prev proposal" if cid == "TK2" else "",
    })
    mocker.patch.object(T, "_check", return_value=(True, ""))
    return T


def test_dry_run_prepares_without_submitting(mocker):
    T = _mock_playwright(mocker)
    submit = mocker.patch.object(T, "_submit", return_value=(True, "ok"))

    res = T.run_tasker_apply(
        category_ids="110", min_charge=5000, max_charge=9000, max_cases=5,
        dry_run=True, proposal_fn=lambda t, d: "MY PROPOSAL", log=lambda m: None,
    )

    assert submit.call_count == 0                     # never submits in dry-run
    assert res["applied_count"] == 1                  # TK1 prepared
    assert res["skipped_count"] == 1                  # TK2 already proposed
    assert res["applied"][0]["status"] == "prepared"
    assert res["applied"][0]["proposal"] == "MY PROPOSAL"
    assert res["skipped"][0]["reason"] == "already proposed"


def test_submit_posts_expected_payload(mocker):
    T = _mock_playwright(mocker)
    submit = mocker.patch.object(T, "_submit", return_value=(True, "ok"))

    res = T.run_tasker_apply(
        category_ids="110", min_charge=5000, max_charge=9000, max_cases=5,
        dry_run=False, proposal_fn=lambda t, d: "MY PROPOSAL", log=lambda m: None,
    )

    submit.assert_called_once()
    _req, _bearer, cid, lo, hi, content = submit.call_args.args
    assert cid == "TK1" and lo == 5000 and hi == 9000 and content == "MY PROPOSAL"
    assert res["submitted_count"] == 1
    assert res["applied"][0]["status"] == "submitted"


def test_ineligible_case_skipped(mocker):
    T = _mock_playwright(mocker)
    mocker.patch.object(T, "_check", return_value=(False, "your own case (您無法對自己的案件提案)"))
    submit = mocker.patch.object(T, "_submit", return_value=(True, "ok"))

    res = T.run_tasker_apply(
        category_ids="110", min_charge=5000, max_charge=9000, max_cases=1,
        dry_run=False, proposal_fn=lambda t, d: "x", log=lambda m: None,
    )
    assert submit.call_count == 0
    assert res["applied_count"] == 0
    assert "own case" in res["skipped"][0]["reason"]


# ── wiring consistency ───────────────────────────────────────────────────────

def test_job_type_wired_everywhere():
    from src.automation.executor import _FLOW_MAP
    from src.automation.harness.validator import _CHECKS
    from src.routers.system import _CATALOG

    assert "tasker_apply" in _FLOW_MAP
    assert "tasker_apply" in _CHECKS

    job_types = {i.get("job_type") for cat in _CATALOG.values() for i in cat}
    assert "tasker_apply" in job_types
