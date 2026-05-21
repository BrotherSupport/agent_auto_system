from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.crews.x_scraper_crew.crew import XScraperCrew
from src.automation.flows.utils import extract_usage
from src.automation.progress import append_log




class XScraperState(BaseModel):
    username: str = ""
    limit: int = 5
    run_id: int = 0
    usage: dict = {}
    llm_provider: str = ""
    llm_model: str = ""


class XScraperFlow(Flow[XScraperState]):

    @start()
    def validate_payload(self):
        if not self.state.username:
            raise ValueError("Missing required field: username")
        append_log(self.state.run_id, f"Validated payload for @{self.state.username}")
        return self.state.model_dump()

    @listen(validate_payload)
    def execute_crew(self, _):
        from src.automation.harness.provider import resolve as resolve_llm
        llm, _, _ = resolve_llm(self.state.llm_provider or None, self.state.llm_model or None)
        append_log(self.state.run_id, "Fetching posts via nitter...")
        crew = XScraperCrew(llm=llm)
        result = crew.crew().kickoff(inputs={
            "username": self.state.username,
            "limit": self.state.limit,
        })
        self.state.usage = extract_usage(result)
        append_log(self.state.run_id, "Analysis complete, formatting result...")
        return result.raw if hasattr(result, "raw") else str(result)
