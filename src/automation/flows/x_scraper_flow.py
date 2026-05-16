from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.crews.x_scraper_crew.crew import XScraperCrew
from src.automation.progress import append_log


class XScraperState(BaseModel):
    username: str = ""
    limit: int = 5
    run_id: int = 0


class XScraperFlow(Flow[XScraperState]):

    @start()
    def validate_payload(self):
        if not self.state.username:
            raise ValueError("Missing required field: username")
        append_log(self.state.run_id, f"Validated payload for @{self.state.username}")
        return self.state.model_dump()

    @listen(validate_payload)
    def execute_crew(self, _):
        append_log(self.state.run_id, f"Fetching posts via nitter...")
        result = XScraperCrew().crew().kickoff(inputs={
            "username": self.state.username,
            "limit": self.state.limit,
        })
        append_log(self.state.run_id, "Analysis complete, formatting result...")
        return result.raw if hasattr(result, "raw") else str(result)
