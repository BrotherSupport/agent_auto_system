"""Quality evaluation ("evaluate node") for automation results.

Runs after validation and is purely informational — it never changes a run's
success/failed status. Produces a 0-100 quality score with a 0-1 confidence
using an LLM-as-judge, falling back to a deterministic heuristic when no LLM is
available (missing API key, network error, or unparseable judge output).
"""
import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL | re.IGNORECASE)
_MAX_RESULT_CHARS = 6000


@dataclass
class EvalResult:
    score: float           # 0-100 overall quality
    confidence: float      # 0-1 confidence in the score
    notes: str = ""
    method: str = "heuristic"  # "llm" | "heuristic"


_JUDGE_PROMPT = """You are a strict quality evaluator for an automation system.
A "{job_type}" automation job produced the following JSON result:

{result}

Rate the result's quality and completeness for this job type. Consider whether
the expected fields are present, the content is substantive and on-topic, and
there are no signs of failure, truncation, or hallucination.

Respond with ONLY a JSON object (no markdown fences) with exactly these keys:
- "score": integer 0-100 (100 = excellent, 0 = unusable)
- "confidence": number between 0.0 and 1.0 (how sure you are of the score)
- "notes": one short sentence explaining the score
"""


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _parse_json(text: str) -> dict | None:
    for candidate in (text, _strip_fence(text)):
        if candidate is None:
            continue
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _strip_fence(text: str) -> str | None:
    if not isinstance(text, str):
        return None
    m = _FENCE_RE.match(text)
    return m.group(1) if m else None


def _heuristic(job_type: str, result) -> EvalResult:
    """Deterministic completeness-based score used when no LLM judge is available."""
    if not isinstance(result, dict):
        return EvalResult(0.0, 1.0, "result is not a dict", "heuristic")
    if result.get("error"):
        return EvalResult(0.0, 1.0, f"result contains error: {result['error']}", "heuristic")

    non_empty = [v for v in result.values() if v]
    content_len = len(" ".join(str(v) for v in non_empty))
    field_score = min(len(non_empty) * 12, 60)       # up to 60 for ~5 populated fields
    length_score = min(content_len / 40.0, 40.0)     # up to 40 for ~1600 chars
    score = round(min(field_score + length_score, 100.0), 1)
    return EvalResult(
        score, 0.4,
        f"heuristic: {len(non_empty)} populated field(s), {content_len} chars",
        "heuristic",
    )


def evaluate(job_type: str, result, provider: str | None = None, model: str | None = None) -> EvalResult:
    """Score the quality of a job result. Never raises — falls back to a heuristic."""
    # An errored result is a known failure; don't spend an LLM call to judge it.
    if isinstance(result, dict) and result.get("error"):
        return _heuristic(job_type, result)

    try:
        from src.automation.harness.provider import resolve

        llm, _, _ = resolve(provider or None, model or None, temperature=0.0)
        result_json = json.dumps(result, ensure_ascii=False)[:_MAX_RESULT_CHARS]
        prompt = _JUDGE_PROMPT.format(job_type=job_type, result=result_json)

        raw = llm.call(prompt)
        data = _parse_json(raw if isinstance(raw, str) else str(raw))
        if not data:
            raise ValueError("judge returned unparseable output")

        score = _clamp(float(data.get("score", 0)), 0.0, 100.0)
        confidence = _clamp(float(data.get("confidence", 0)), 0.0, 1.0)
        notes = str(data.get("notes", "")).strip()[:500]
        return EvalResult(round(score, 1), round(confidence, 3), notes, "llm")
    except Exception as exc:  # noqa: BLE001 — evaluation must never break a run
        logger.warning("LLM evaluation failed (%s); using heuristic fallback", exc)
        ev = _heuristic(job_type, result)
        if not ev.notes:
            ev.notes = f"heuristic fallback ({exc})"
        return ev
