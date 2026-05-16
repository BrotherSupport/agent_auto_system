from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.crews.hn_digest_crew.crew import HNDigestCrew
from src.automation.progress import append_log


class HNDigestState(BaseModel):
    limit: int = 5
    run_id: int = 0


class HNDigestFlow(Flow[HNDigestState]):

    @start()
    def validate_payload(self):
        if not 1 <= self.state.limit <= 10:
            raise ValueError("limit must be between 1 and 10")
        append_log(self.state.run_id, f"Fetching top {self.state.limit} HN stories...")
        return self.state.model_dump()

    @listen(validate_payload)
    def execute_crew(self, _):
        append_log(self.state.run_id, "HN analyst agent reading stories...")
        result = HNDigestCrew().crew().kickoff(inputs={
            "limit": self.state.limit,
        })
        append_log(self.state.run_id, "Digest generated, formatting result...")
        return result.raw if hasattr(result, "raw") else str(result)
