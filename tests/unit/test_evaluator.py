from src.automation.harness.evaluator import EvalResult, _heuristic, _parse_json, evaluate


class _FakeLLM:
    def __init__(self, response):
        self._response = response

    def call(self, prompt):
        return self._response


# ── heuristic ────────────────────────────────────────────────────────────────

def test_heuristic_scores_populated_dict():
    ev = _heuristic("web_scraper", {"title": "T", "summary": "S" * 200, "links": ["a", "b"]})
    assert ev.method == "heuristic"
    assert 0 < ev.score <= 100
    assert 0 <= ev.confidence <= 1


def test_heuristic_error_result_is_zero():
    ev = _heuristic("web_scraper", {"error": "boom"})
    assert ev.score == 0.0
    assert ev.confidence == 1.0


def test_heuristic_non_dict_is_zero():
    ev = _heuristic("web_scraper", "not a dict")
    assert ev.score == 0.0


# ── _parse_json ──────────────────────────────────────────────────────────────

def test_parse_json_plain():
    assert _parse_json('{"score": 80}') == {"score": 80}


def test_parse_json_strips_fence():
    assert _parse_json('```json\n{"score": 80}\n```') == {"score": 80}


def test_parse_json_garbage_returns_none():
    assert _parse_json("not json at all") is None


# ── evaluate ───────────────────────────────────────────────────────────────--

def test_evaluate_error_result_short_circuits_without_llm(mocker):
    resolve = mocker.patch("src.automation.harness.provider.resolve")
    ev = evaluate("web_scraper", {"error": "fetch failed"})
    assert ev.method == "heuristic"
    assert ev.score == 0.0
    resolve.assert_not_called()


def test_evaluate_llm_path_parses_score(mocker):
    fake = _FakeLLM('{"score": 87, "confidence": 0.92, "notes": "complete"}')
    mocker.patch("src.automation.harness.provider.resolve", return_value=(fake, "openai", "gpt-4o-mini"))
    ev = evaluate("web_scraper", {"title": "T", "summary": "S"})
    assert ev.method == "llm"
    assert ev.score == 87.0
    assert ev.confidence == 0.92
    assert ev.notes == "complete"


def test_evaluate_llm_path_clamps_out_of_range(mocker):
    fake = _FakeLLM('{"score": 150, "confidence": 3}')
    mocker.patch("src.automation.harness.provider.resolve", return_value=(fake, "openai", "gpt-4o-mini"))
    ev = evaluate("web_scraper", {"title": "T"})
    assert ev.score == 100.0
    assert ev.confidence == 1.0


def test_evaluate_falls_back_to_heuristic_on_resolve_error(mocker):
    mocker.patch("src.automation.harness.provider.resolve", side_effect=OSError("no api key"))
    ev = evaluate("web_scraper", {"title": "T", "summary": "S" * 100})
    assert ev.method == "heuristic"
    assert isinstance(ev, EvalResult)


def test_evaluate_falls_back_when_judge_output_unparseable(mocker):
    fake = _FakeLLM("I think it's pretty good honestly")
    mocker.patch("src.automation.harness.provider.resolve", return_value=(fake, "openai", "gpt-4o-mini"))
    ev = evaluate("web_scraper", {"title": "T", "summary": "S"})
    assert ev.method == "heuristic"
