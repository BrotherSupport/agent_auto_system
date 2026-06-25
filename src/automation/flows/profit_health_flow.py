import csv
import io
import json

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.flows.base import FlowMixin
from src.automation.profit_health_schema import ADS_COMMENT_PREFIX, JOB_TYPE
from src.automation.progress import append_log
from src.routers.uploads import UPLOAD_ROOT


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


def _read_csv(upload_id: str, filename: str) -> str:
    path = UPLOAD_ROOT / upload_id / filename
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _csv_stats(text: str, skip_comment: bool = False) -> dict:
    """Lightweight row/column count for the Phase 2 stub."""
    if not text.strip():
        return {"rows": 0, "columns": 0}
    lines = text.splitlines()
    if skip_comment and lines and lines[0].lstrip().startswith(ADS_COMMENT_PREFIX):
        lines = lines[1:]
    reader = csv.reader(io.StringIO("\n".join(lines)))
    header = next(reader, [])
    rows = sum(1 for _ in reader)
    return {"rows": rows, "columns": len(header)}


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

        append_log(self.state.run_id, f"Loaded CSVs from upload {self.state.upload_id}")
        return self.state.model_dump()

    @listen(validate_payload)
    def execute_crew(self, _):
        # Phase 2 stub: prove the create-job → run → result loop end-to-end.
        # Replaced by the multi-agent crew in Phase 4.
        files = {
            "sales":   _csv_stats(self.state.sales_csv),
            "cost":    _csv_stats(self.state.cost_csv),
            "ads":     _csv_stats(self.state.ads_csv, skip_comment=True),
            "returns": _csv_stats(self.state.returns_csv),
        }
        append_log(self.state.run_id, "Stub: counted CSV rows/columns (crew not wired yet)")
        return json.dumps({
            "stub": True,
            "job_type": JOB_TYPE,
            "summary": "Phase 2 skeleton — CSVs loaded and parsed; analysis crew not wired yet.",
            "files": files,
        }, ensure_ascii=False)
