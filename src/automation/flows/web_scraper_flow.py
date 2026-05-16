from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.crews.web_scraper_crew.crew import WebScraperCrew
from src.automation.progress import append_log


class WebScraperState(BaseModel):
    url: str = ""
    question: str = "What is this page about?"
    run_id: int = 0


class WebScraperFlow(Flow[WebScraperState]):

    @start()
    def validate_payload(self):
        if not self.state.url:
            raise ValueError("Missing required field: url")
        append_log(self.state.run_id, f"Payload validated, fetching {self.state.url}...")
        return self.state.model_dump()

    @listen(validate_payload)
    def execute_crew(self, _):
        append_log(self.state.run_id, "Web scraper agent reading page content...")
        result = WebScraperCrew().crew().kickoff(inputs={
            "url": self.state.url,
            "question": self.state.question,
        })
        append_log(self.state.run_id, "Agent generated answer, formatting result...")
        return result.raw if hasattr(result, "raw") else str(result)
