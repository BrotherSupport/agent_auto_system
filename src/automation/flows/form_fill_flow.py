from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.crews.form_crew.crew import FormFillerCrew
from src.automation.progress import append_log


def _extract_usage(result) -> dict:
    m = getattr(result, "usage_metrics", None)
    if not m:
        return {}
    return {
        "prompt_tokens":     getattr(m, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(m, "completion_tokens", 0) or 0,
    }


class FormFillState(BaseModel):
    company_name: str = ""
    company_size: str = ""
    ai_problem: str = ""
    run_id: int = 0
    usage: dict = {}
    llm_provider: str = ""
    llm_model: str = ""


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
        from src.automation.harness.provider import resolve as resolve_llm
        llm, _, _ = resolve_llm(self.state.llm_provider or None, self.state.llm_model or None)
        append_log(self.state.run_id, "Inspecting Google Form structure...")
        crew = FormFillerCrew()
        crew.llm = llm
        result = crew.crew().kickoff(inputs={
            "company_name": self.state.company_name,
            "company_size": self.state.company_size,
            "ai_problem": self.state.ai_problem,
        })
        self.state.usage = _extract_usage(result)
        append_log(self.state.run_id, "Form submission attempted, reading result...")
        return result.raw if hasattr(result, "raw") else str(result)
