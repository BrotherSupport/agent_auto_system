from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.crews.hn_digest_crew.crew import HNDigestCrew


class HNDigestState(BaseModel):
    limit: int = 5


class HNDigestFlow(Flow[HNDigestState]):

    @start()
    def validate_payload(self):
        if not 1 <= self.state.limit <= 10:
            raise ValueError("limit must be between 1 and 10")
        return self.state.model_dump()

    @listen(validate_payload)
    def execute_crew(self, _):
        result = HNDigestCrew().crew().kickoff(inputs={
            "limit": self.state.limit,
        })
        return result.raw if hasattr(result, "raw") else str(result)
