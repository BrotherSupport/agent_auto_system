from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.crews.web_scraper_crew.crew import WebScraperCrew
from src.automation.progress import append_log


def _extract_usage(result) -> dict:
    m = getattr(result, "usage_metrics", None)
    if not m:
        return {}
    return {
        "prompt_tokens":     getattr(m, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(m, "completion_tokens", 0) or 0,
    }


class WebScraperState(BaseModel):
    url: str = ""
    run_id: int = 0
    usage: dict = {}
    llm_provider: str = ""
    llm_model: str = ""


class WebScraperFlow(Flow[WebScraperState]):

    @start()
    def validate_payload(self):
        if not self.state.url:
            raise ValueError("Missing required field: url")
        append_log(self.state.run_id, f"Payload validated, fetching {self.state.url}...")
        return self.state.model_dump()

    @listen(validate_payload)
    def execute_crew(self, _):
        from src.automation.harness.provider import resolve as resolve_llm
        llm, _, _ = resolve_llm(self.state.llm_provider or None, self.state.llm_model or None)
        append_log(self.state.run_id, "Web scraper agent reading page content...")
        crew = WebScraperCrew(llm=llm)
        result = crew.crew().kickoff(inputs={"url": self.state.url})
        self.state.usage = _extract_usage(result)
        append_log(self.state.run_id, "Agent generated summary, formatting result...")
        return result.raw if hasattr(result, "raw") else str(result)
