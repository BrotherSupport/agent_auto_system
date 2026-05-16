from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.crews.form_crew.crew import FormFillerCrew
from src.automation.progress import append_log


class FormFillState(BaseModel):
    company_name: str = ""
    company_size: str = ""
    ai_problem: str = ""
    run_id: int = 0


class FormFillFlow(Flow[FormFillState]):

    @start()
    def validate_payload(self):
        missing = [
            f for f in ("company_name", "company_size", "ai_problem")
            if not getattr(self.state, f, "")
        ]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")
        append_log(self.state.run_id, "Payload validated, launching form agent...")
        return self.state.model_dump()

    @listen(validate_payload)
    def execute_crew(self, _):
        append_log(self.state.run_id, "Inspecting Google Form structure...")
        result = FormFillerCrew().crew().kickoff(inputs={
            "company_name": self.state.company_name,
            "company_size": self.state.company_size,
            "ai_problem": self.state.ai_problem,
        })
        append_log(self.state.run_id, "Form submission attempted, reading result...")
        return result.raw if hasattr(result, "raw") else str(result)
