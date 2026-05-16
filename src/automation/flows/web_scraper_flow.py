from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.crews.web_scraper_crew.crew import WebScraperCrew


class WebScraperState(BaseModel):
    url: str = ""
    question: str = "What is this page about?"


class WebScraperFlow(Flow[WebScraperState]):

    @start()
    def validate_payload(self):
        if not self.state.url:
            raise ValueError("Missing required field: url")
        return self.state.model_dump()

    @listen(validate_payload)
    def execute_crew(self, _):
        result = WebScraperCrew().crew().kickoff(inputs={
            "url": self.state.url,
            "question": self.state.question,
        })
        return result.raw if hasattr(result, "raw") else str(result)
