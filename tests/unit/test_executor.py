import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session

from src.models import Job, Run

# _run_flow returns (result, usage, serve); serve carries fallback metadata.
_SERVE = {"served_model": "test/model", "models_attempted": 1, "fallback_used": False}


@pytest.fixture
def seeded_run(test_engine):
    with Session(test_engine) as s:
        job = Job(name="test", job_type="hacker_news_digest", payload=json.dumps({"limit": 5}))
        s.add(job)
        s.commit()
        s.refresh(job)
        run = Run(job_id=job.id, status="pending")
        s.add(run)
        s.commit()
        s.refresh(run)
        return run.id


def _get_run(engine, run_id):
    with Session(engine) as s:
        return s.get(Run, run_id)


async def test_execute_run_success(test_engine, seeded_run, mocker):
    mocker.patch("src.automation.executor.get_engine", return_value=test_engine)
    mocker.patch("src.automation.progress.append_log")
    mocker.patch(
        "src.automation.executor._run_flow",
        new=AsyncMock(return_value=(
            {"digest": "Top HN stories today about AI and Rust", "stories": [1, 2, 3]},
            {"prompt_tokens": 100, "completion_tokens": 50},
            _SERVE,
        )),
    )

    from src.automation.executor import execute_run
    await execute_run(seeded_run, "hacker_news_digest", {"limit": 3})

    run = _get_run(test_engine, seeded_run)
    assert run.status == "success"
    assert run.tokens_in == 100
    assert run.tokens_out == 50
    assert run.retry_count == 0
    # Tier 2 columns persisted from the serve dict + validation gate
    assert run.served_model == "test/model"
    assert run.fallback_used is False
    assert run.models_attempted == 1
    assert run.validation_passed is True
    assert run.duration_secs is not None


async def test_execute_run_validation_fail_then_retry_success(test_engine, seeded_run, mocker):
    mocker.patch("src.automation.executor.get_engine", return_value=test_engine)
    mocker.patch("src.automation.progress.append_log")

    call_count = 0

    async def side_effect(run_id, job_type, payload, provider, model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ({"error": "first attempt failed"}, {}, _SERVE)
        return (
            {"digest": "Stories on attempt two today!", "stories": [1]},
            {"prompt_tokens": 10, "completion_tokens": 5},
            _SERVE,
        )

    mocker.patch("src.automation.executor._run_flow", side_effect=side_effect)

    from src.automation.executor import execute_run
    await execute_run(seeded_run, "hacker_news_digest", {"max_retries": 1, "limit": 3})

    run = _get_run(test_engine, seeded_run)
    assert run.status == "success"
    assert call_count == 2
    assert run.retry_count == 1


async def test_execute_run_all_retries_exhausted(test_engine, seeded_run, mocker):
    mocker.patch("src.automation.executor.get_engine", return_value=test_engine)
    mocker.patch("src.automation.progress.append_log")
    mocker.patch(
        "src.automation.executor._run_flow",
        new=AsyncMock(return_value=({"error": "always fails"}, {}, _SERVE)),
    )

    from src.automation.executor import execute_run
    await execute_run(seeded_run, "hacker_news_digest", {"max_retries": 2, "limit": 3})

    run = _get_run(test_engine, seeded_run)
    assert run.status == "failed"
    assert run.retry_count == 2


async def test_execute_run_exception_marks_failed(test_engine, seeded_run, mocker):
    mocker.patch("src.automation.executor.get_engine", return_value=test_engine)
    mocker.patch("src.automation.progress.append_log")
    mocker.patch(
        "src.automation.executor._run_flow",
        new=AsyncMock(side_effect=RuntimeError("connection refused")),
    )

    from src.automation.executor import execute_run
    await execute_run(seeded_run, "hacker_news_digest", {"max_retries": 0, "limit": 3})

    run = _get_run(test_engine, seeded_run)
    assert run.status == "failed"
    result = json.loads(run.result)
    assert "connection refused" in result["error"]


async def test_execute_run_cancelled_error_propagates(test_engine, seeded_run, mocker):
    mocker.patch("src.automation.executor.get_engine", return_value=test_engine)
    mocker.patch("src.automation.progress.append_log")
    mocker.patch(
        "src.automation.executor._run_flow",
        new=AsyncMock(side_effect=asyncio.CancelledError()),
    )

    from src.automation.executor import execute_run
    with pytest.raises(asyncio.CancelledError):
        await execute_run(seeded_run, "hacker_news_digest", {"limit": 3})


async def test_previous_error_injected_on_retry(test_engine, seeded_run, mocker):
    mocker.patch("src.automation.executor.get_engine", return_value=test_engine)
    mocker.patch("src.automation.progress.append_log")

    captured_payloads: list[dict] = []

    async def capture(run_id, job_type, payload, provider, model):
        captured_payloads.append(dict(payload))
        if len(captured_payloads) == 1:
            return ({"error": "first attempt"}, {}, _SERVE)
        return (
            {"digest": "Fixed now, all stories included today!", "stories": [1]},
            {"prompt_tokens": 5, "completion_tokens": 5},
            _SERVE,
        )

    mocker.patch("src.automation.executor._run_flow", side_effect=capture)

    from src.automation.executor import execute_run
    await execute_run(seeded_run, "hacker_news_digest", {"max_retries": 1, "limit": 3})

    assert len(captured_payloads) == 2
    assert "previous_error" in captured_payloads[1]
    assert captured_payloads[1]["previous_error"]


@pytest.fixture
def seeded_pipeline_run(test_engine):
    with Session(test_engine) as s:
        job = Job(
            name="pipeline test",
            job_type="pipeline",
            payload=json.dumps({
                "steps": [
                    {"job_type": "hacker_news_digest", "payload": {"limit": 3}},
                ]
            }),
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        run = Run(job_id=job.id, status="pending")
        s.add(run)
        s.commit()
        s.refresh(run)
        return run.id


async def test_execute_run_dispatches_to_pipeline(test_engine, seeded_pipeline_run, mocker):
    mocker.patch("src.automation.executor.get_engine", return_value=test_engine)
    mocker.patch("src.automation.progress.append_log")
    mock_execute_pipeline = mocker.patch(
        "src.automation.executor.execute_pipeline",
        new=AsyncMock(return_value=(
            {
                "steps": [{"step": 1, "job_type": "hacker_news_digest", "result": {"digest": "Top stories today", "stories": [1]}}],
                "final_result": {"digest": "Top stories today", "stories": [1]},
            },
            {"prompt_tokens": 50, "completion_tokens": 25},
        )),
    )

    from src.automation.executor import execute_run
    await execute_run(
        seeded_pipeline_run,
        "pipeline",
        {"steps": [{"job_type": "hacker_news_digest", "payload": {"limit": 3}}]},
    )

    run = _get_run(test_engine, seeded_pipeline_run)
    assert run.status == "success"
    assert mock_execute_pipeline.called


async def test_execute_run_pipeline_unknown_type_falls_through(test_engine, seeded_run, mocker):
    mocker.patch("src.automation.executor.get_engine", return_value=test_engine)
    mocker.patch("src.automation.progress.append_log")
    mocker.patch(
        "src.automation.executor._run_flow",
        new=AsyncMock(side_effect=ValueError("Unknown job_type: nonexistent_type")),
    )

    from src.automation.executor import execute_run
    await execute_run(seeded_run, "nonexistent_type", {"max_retries": 0})

    run = _get_run(test_engine, seeded_run)
    assert run.status == "failed"


class _FakeRaw:
    def __init__(self, raw):
        self.raw = raw


def _register_fake_flow(mocker, kickoff):
    """Wire a fake flow class so _run_flow('__test__', ...) drives `kickoff`."""
    import sys
    import types

    state = types.SimpleNamespace(usage={"prompt_tokens": 1, "completion_tokens": 2})

    class FakeFlow:
        def __init__(self):
            self.state = state

        def kickoff(self, inputs=None):
            return kickoff(inputs)

    mod = types.ModuleType("fake_flow_mod")
    mod.FakeFlow = FakeFlow
    sys.modules["fake_flow_mod"] = mod

    from src.automation import executor
    mocker.patch.dict(executor._FLOW_MAP, {"__test__": ("fake_flow_mod", "FakeFlow", "log")})
    mocker.patch("src.automation.executor.asyncio.sleep", new=AsyncMock())


async def test_run_flow_retries_then_falls_back_on_unavailable(mocker):
    mocker.patch("src.automation.progress.append_log")
    seen: list[str] = []

    def kickoff(inputs):
        seen.append(inputs["llm_model"])
        if len(seen) < 3:
            raise RuntimeError("503 UNAVAILABLE: model experiencing high demand, try again")
        return _FakeRaw('{"sellers": [{"shop_name": "x"}], "summary": "ok"}')

    _register_fake_flow(mocker, kickoff)

    from src.automation.executor import _run_flow
    result, usage, serve = await _run_flow(0, "__test__", {}, "gemini", "gemini/gemini-2.5-flash")

    assert result["sellers"]
    assert len(seen) == 3
    # primary tried twice, then a same-provider fallback
    assert seen[0] == seen[1] == "gemini/gemini-2.5-flash"
    assert seen[2] != "gemini/gemini-2.5-flash"
    # serve metadata reflects the failover
    assert serve["served_model"] == seen[2]
    assert serve["fallback_used"] is True
    assert serve["models_attempted"] == 2


async def test_run_flow_non_retriable_error_raises_immediately(mocker):
    mocker.patch("src.automation.progress.append_log")
    calls = {"n": 0}

    def kickoff(inputs):
        calls["n"] += 1
        raise RuntimeError("401 invalid api key")

    _register_fake_flow(mocker, kickoff)

    from src.automation.executor import _run_flow
    with pytest.raises(RuntimeError, match="invalid api key"):
        await _run_flow(0, "__test__", {}, "gemini", "gemini/gemini-2.5-flash")
    assert calls["n"] == 1  # no retries for a hard error


async def test_run_flow_raises_after_exhausting_attempts(mocker):
    mocker.patch("src.automation.progress.append_log")
    from src.automation.harness.provider import MAX_LLM_ATTEMPTS
    calls = {"n": 0}

    def kickoff(inputs):
        calls["n"] += 1
        raise RuntimeError("503 model unavailable, high demand")

    _register_fake_flow(mocker, kickoff)

    from src.automation.executor import _run_flow
    with pytest.raises(RuntimeError, match="unavailable"):
        await _run_flow(0, "__test__", {}, "gemini", "gemini/gemini-2.5-flash")
    assert calls["n"] == MAX_LLM_ATTEMPTS


def test_parse_result_plain_json():
    from src.automation.executor import _parse_result
    assert _parse_result('{"title": "x", "summary": "y"}') == {"title": "x", "summary": "y"}


def test_parse_result_strips_json_fence():
    from src.automation.executor import _parse_result
    fenced = '```json\n{"title": "x", "summary": "y"}\n```'
    assert _parse_result(fenced) == {"title": "x", "summary": "y"}


def test_parse_result_strips_bare_fence():
    from src.automation.executor import _parse_result
    fenced = '```\n{"title": "x"}\n```'
    assert _parse_result(fenced) == {"title": "x"}


def test_parse_result_non_json_falls_back_to_message():
    from src.automation.executor import _parse_result
    assert _parse_result("hello world") == {"message": "hello world"}


async def test_execute_run_persists_eval_fields(test_engine, seeded_run, mocker):
    mocker.patch("src.automation.executor.get_engine", return_value=test_engine)
    mocker.patch("src.automation.progress.append_log")
    mocker.patch(
        "src.automation.executor._run_flow",
        new=AsyncMock(return_value=(
            {"digest": "Top HN stories today", "stories": [1, 2]},
            {"prompt_tokens": 10, "completion_tokens": 5},
            _SERVE,
        )),
    )

    from src.automation.executor import execute_run
    await execute_run(seeded_run, "hacker_news_digest", {"limit": 3})

    run = _get_run(test_engine, seeded_run)
    assert run.status == "success"
    # eval node runs after validation and is stubbed by the autouse fixture
    assert run.eval_score == 90.0
    assert run.eval_confidence == 0.9
    assert run.eval_method == "heuristic"
