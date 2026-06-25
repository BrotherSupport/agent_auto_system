from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.crews.profit_health_crew.crew import ProfitHealthCrew
from src.automation.flows.base import FlowMixin
from src.automation.flows.utils import extract_usage
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
        from src.automation.harness.provider import resolve as resolve_llm
        llm, _, _ = resolve_llm(
            self.state.llm_provider or None,
            self.state.llm_model or None,
            temperature=0.2,
        )
        append_log(self.state.run_id, "驗證 → 修正 → 分析 → 建議 (4-agent crew)...")
        crew = ProfitHealthCrew(llm=llm)
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
