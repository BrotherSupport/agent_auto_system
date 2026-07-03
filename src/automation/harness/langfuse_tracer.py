"""Langfuse LLM-observability integration.

Emits one Langfuse trace per automation run from the executor — the single
funnel that already knows the model, token usage, cost, eval score, and final
status. CrewAI 1.x calls native provider SDKs (OpenAI/Anthropic/Gemini), *not*
litellm, so tracing at the executor level is provider-agnostic and doesn't
couple us to CrewAI internals or a version-specific auto-instrumentor.

Enabled automatically when ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY``
are set (and ``LANGFUSE_ENABLED`` != "false"). A no-op otherwise, and it never
raises — observability must never break a run.

Env vars (see .env.example):
  LANGFUSE_PUBLIC_KEY   pk-lf-...                    (required)
  LANGFUSE_SECRET_KEY   sk-lf-...                    (required)
  LANGFUSE_HOST         https://cloud.langfuse.com   (optional; EU cloud default)
  LANGFUSE_ENABLED      "false" disables even when keys are present
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "https://cloud.langfuse.com"

_client: Any = None
_init_attempted = False


def is_configured() -> bool:
    """True when both keys are present and Langfuse isn't explicitly disabled."""
    if os.getenv("LANGFUSE_ENABLED", "true").lower() == "false":
        return False
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def get_client():
    """Lazily build a singleton Langfuse client, or return None when unconfigured
    or unavailable. Memoized so we construct (and authenticate) at most once."""
    global _client, _init_attempted
    if _init_attempted:
        return _client
    _init_attempted = True

    if not is_configured():
        return None

    host = os.getenv("LANGFUSE_HOST", _DEFAULT_HOST)
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            host=host,
        )
        logger.info("Langfuse tracing enabled (host=%s).", host)
    except Exception:  # noqa: BLE001 — never let observability break startup
        logger.exception("Failed to initialise Langfuse client; tracing disabled.")
        _client = None
    return _client


def reset() -> None:
    """Testing hook: drop the memoized client so env changes take effect again."""
    global _client, _init_attempted
    _client, _init_attempted = None, False


def flush() -> None:
    """Block until buffered events are sent. Safe to call when disabled."""
    client = get_client()
    if client is not None:
        try:
            client.flush()
        except Exception:  # noqa: BLE001
            logger.debug("Langfuse flush failed; ignoring.", exc_info=True)


def record_run(
    *,
    run_id: int,
    job_type: str,
    status: str,
    provider: str,
    model: str,
    payload: dict | None = None,
    result: dict | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    duration_secs: float | None = None,
    eval_score: float | None = None,
    eval_confidence: float | None = None,
    eval_notes: str = "",
) -> str | None:
    """Emit one trace (root span + nested LLM generation) for a finished run.

    ``status`` is "success" or "failed". Returns the Langfuse trace URL when a
    trace was sent, else None. Never raises — all errors are swallowed so a
    tracing failure can't fail the run.
    """
    client = get_client()
    if client is None:
        return None

    try:
        # Seed the trace id from run_id so a run maps to exactly one stable trace
        # (and we can build its URL) even if record_run is reached more than once.
        trace_id = client.create_trace_id(seed=str(run_id))
        level = "ERROR" if status == "failed" else "DEFAULT"
        status_message = None
        if status == "failed" and isinstance(result, dict):
            status_message = str(result.get("error") or "run failed")[:500]

        metadata: dict[str, Any] = {
            "run_id": run_id,
            "job_type": job_type,
            "provider": provider,
            "status": status,
        }
        if duration_secs is not None:
            metadata["duration_secs"] = round(duration_secs, 3)

        # Tags make runs filterable in the Langfuse UI. The root span's name and
        # input/output automatically become the trace's, so no set_trace_io.
        from langfuse import propagate_attributes

        with propagate_attributes(trace_name=f"run:{job_type}",
                                  tags=[job_type, provider, status]):
            root = client.start_observation(
                trace_context={"trace_id": trace_id},
                name=f"run:{job_type}",
                as_type="span",
                input=payload,
                output=result,
                metadata=metadata,
                level=level,
                status_message=status_message,
            )
            try:
                gen = root.start_observation(
                    name=f"{provider}/{model}",
                    as_type="generation",
                    model=model,
                    input=payload,
                    output=result,
                    usage_details={
                        "input": tokens_in,
                        "output": tokens_out,
                        "total": tokens_in + tokens_out,
                    },
                    cost_details={"total": cost_usd},
                    level=level,
                    status_message=status_message,
                )
                gen.end()

                # Attach the evaluator's quality signals as trace scores.
                if eval_score is not None:
                    root.score_trace(name="eval_score", value=float(eval_score),
                                     comment=eval_notes or None)
                if eval_confidence is not None:
                    root.score_trace(name="eval_confidence", value=float(eval_confidence))
            finally:
                root.end()

        client.flush()
    except Exception:  # noqa: BLE001
        logger.exception("Langfuse record_run failed for run_id=%s; ignoring.", run_id)
        return None

    # The trace is already recorded above; the URL is a best-effort convenience
    # (it does a one-off project-id lookup that can fail on its own).
    try:
        return client.get_trace_url(trace_id=trace_id)
    except Exception:  # noqa: BLE001
        logger.debug("Langfuse get_trace_url failed for run_id=%s; ignoring.", run_id,
                     exc_info=True)
        return None
