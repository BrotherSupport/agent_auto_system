from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.crews.form_crew.crew import FormFillerCrew


class FormFillState(BaseModel):
    company_name: str = ""
    company_size: str = ""
    ai_problem: str = ""


class FormFillFlow(Flow[FormFillState]):

    @start()
    def validate_payload(self):
        missing = [
            f for f in ("company_name", "company_size", "ai_problem")
            if not getattr(self.state, f, "")
        ]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")
        return self.state.model_dump()

    @listen(validate_payload)
    def execute_crew(self, _):
        result = FormFillerCrew().crew().kickoff(inputs={
            "company_name": self.state.company_name,
            "company_size": self.state.company_size,
            "ai_problem": self.state.ai_problem,
        })
        return result.raw if hasattr(result, "raw") else str(result)
