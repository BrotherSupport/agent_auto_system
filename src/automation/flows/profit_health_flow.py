import json
import logging
import re

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.crews.profit_health_crew.crew import ProfitHealthCrew
from src.automation.flows.base import FlowMixin
from src.automation.flows.utils import extract_usage
from src.automation.progress import append_log
from src.automation.report_render import REPORTS_ROOT, render_report_pdf
from src.routers.uploads import UPLOAD_ROOT

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL | re.IGNORECASE)


def _parse_report(raw: str) -> dict | None:
    """Best-effort parse of the crew's raw output into a report dict (or None)."""
    for candidate in (raw, (_FENCE_RE.match(raw).group(1) if isinstance(raw, str) and _FENCE_RE.match(raw) else None)):
        if candidate is None:
            continue
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except (json.JSONDecodeError, TypeError):
            continue
    return None


class ProfitHealthState(BaseModel):
    upload_id: str = ""
    # CSV contents loaded from uploads/<upload_id>/ during validate_payload.
    sales_csv: str = ""
    cost_csv: str = ""
    ads_csv: str = ""
    returns_csv: str = ""
    # Harness-managed fields (must be declared to survive kickoff(inputs=...)).
    run_id: int = 0
    usage: dict = {}
    llm_provider: str = ""
    llm_model: str = ""
    previous_error: str = ""


# The validator/corrector agents only need a sample to check schema and columns;
# the profit_calc tool reads the full files from disk for the actual numbers. Cap
# the prompt-embedded copy so a large upload can't blow the LLM context window.
_MAX_PROMPT_LINES = 100


def _read_csv(upload_id: str, filename: str) -> str:
    path = UPLOAD_ROOT / upload_id / filename
    if not path.is_file():
        return ""
    # utf-8-sig strips a UTF-8 BOM if present (common in Shopee/Excel CSV exports);
    # behaves like utf-8 when absent.
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _truncate_csv(content: str, max_lines: int = _MAX_PROMPT_LINES) -> str:
    if not content:
        return ""
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content
    return "\n".join(lines[:max_lines]) + f"\n... [truncated, {len(lines) - max_lines} more lines] ..."


class ProfitHealthFlow(FlowMixin, Flow[ProfitHealthState]):

    @start()
    def validate_payload(self):
        self._check_required("upload_id")

        dest = UPLOAD_ROOT / self.state.upload_id
        if not dest.is_dir():
            raise ValueError(f"upload not found: {self.state.upload_id}")

        self.state.sales_csv = _read_csv(self.state.upload_id, "sales.csv")
        self.state.cost_csv = _read_csv(self.state.upload_id, "cost.csv")
        self.state.ads_csv = _read_csv(self.state.upload_id, "ads.csv")
        self.state.returns_csv = _read_csv(self.state.upload_id, "returns.csv")

        missing = [n for n, v in (("sales.csv", self.state.sales_csv),
                                  ("cost.csv", self.state.cost_csv)) if not v.strip()]
        if missing:
            raise ValueError(f"Missing required file(s) in upload: {missing}")

        # Cap the prompt-embedded copies; profit_calc still reads full files from disk.
        self.state.sales_csv = _truncate_csv(self.state.sales_csv)
        self.state.cost_csv = _truncate_csv(self.state.cost_csv)
        self.state.ads_csv = _truncate_csv(self.state.ads_csv)
        self.state.returns_csv = _truncate_csv(self.state.returns_csv)

        append_log(self.state.run_id, f"Loaded CSVs from upload {self.state.upload_id}")
        return self.state.model_dump()

    @listen(validate_payload)
    def execute_crew(self, _):
        from src.automation.harness.provider import resolve as resolve_llm
        llm, _, _ = resolve_llm(
            self.state.llm_provider or None,
            self.state.llm_model or None,
            temperature=0.2,
        )
        append_log(self.state.run_id, "驗證 → 修正 → 分析 → 建議 (4-agent crew)...")
        crew = ProfitHealthCrew(llm=llm, run_id=self.state.run_id)
        result = crew.crew().kickoff(inputs={
            "upload_id": self.state.upload_id,
            "sales_csv": self.state.sales_csv,
            "cost_csv": self.state.cost_csv,
            "ads_csv": self.state.ads_csv,
            "returns_csv": self.state.returns_csv,
            "previous_error": self.state.previous_error,
        })
        self.state.usage = extract_usage(result)
        append_log(self.state.run_id, "健檢報告產生完成，整理結果中...")
        return result.raw if hasattr(result, "raw") else str(result)

    @listen(execute_crew)
    def render_pdf(self, raw):
        """Turn the JSON report into a downloadable PDF (json → html → pdf).

        Fail-soft: rendering is presentation only, so any error here just leaves
        the JSON report intact without a pdf_url — it never fails the run.
        """
        report = _parse_report(raw)
        if report is None:
            return raw  # not JSON we can render; pass the crew output through unchanged

        try:
            out_path = REPORTS_ROOT / f"{self.state.run_id}.pdf"
            render_report_pdf(report, out_path)
            report["pdf_url"] = f"/api/runs/{self.state.run_id}/report.pdf"
            append_log(self.state.run_id, "PDF 報告已產生，可於結果頁下載。")
        except Exception as exc:  # noqa: BLE001
            logger.warning("run_id=%s PDF render failed: %s", self.state.run_id, exc)
            append_log(self.state.run_id, f"PDF 產生失敗（報告仍可用）：{str(exc)[:120]}")

        return json.dumps(report, ensure_ascii=False)
