"""OpenTelemetry + Prometheus instrumentation.

Set OTEL_ENABLED=false to skip (default: true).
Mounts /metrics in Prometheus text format when enabled.

Business metrics emitted per run:
  automation_runs_total           {job_type, status}
  automation_run_duration_seconds {job_type}
  automation_tokens_total         {provider, direction}
  automation_cost_usd_total       {provider}
"""
from __future__ import annotations

import os

_ENABLED: bool = os.getenv("OTEL_ENABLED", "true").lower() != "false"

_runs = _duration = _tokens = _cost = None


def setup(app) -> None:
    """Instrument the FastAPI app and mount /metrics. No-op when disabled."""
    if not _ENABLED:
        return
    from opentelemetry import metrics as _m
    from opentelemetry.exporter.prometheus import PrometheusMetricExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from prometheus_client import make_asgi_app

    provider = MeterProvider(metric_readers=[PrometheusMetricExporter()])
    _m.set_meter_provider(provider)
    meter = _m.get_meter("agent-auto-system")

    global _runs, _duration, _tokens, _cost
    _runs     = meter.create_counter("automation_runs_total",
                                     description="Total automation runs")
    _duration = meter.create_histogram("automation_run_duration_seconds",
                                       description="Run wall-clock duration (s)")
    _tokens   = meter.create_counter("automation_tokens_total",
                                     description="LLM tokens consumed")
    _cost     = meter.create_counter("automation_cost_usd_total",
                                     description="Estimated LLM cost USD")

    FastAPIInstrumentor.instrument_app(app)
    app.mount("/metrics", make_asgi_app())


def record_run(
    *,
    job_type: str,
    status: str,
    duration_secs: float,
    provider: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
) -> None:
    """Record business metrics for one completed run. No-op when disabled."""
    if not _ENABLED or _runs is None:
        return
    _runs.add(1, {"job_type": job_type, "status": status})
    _duration.record(duration_secs, {"job_type": job_type})
    if tokens_in:
        _tokens.add(tokens_in,  {"provider": provider, "direction": "in"})
    if tokens_out:
        _tokens.add(tokens_out, {"provider": provider, "direction": "out"})
    if cost_usd:
        _cost.add(cost_usd, {"provider": provider})
