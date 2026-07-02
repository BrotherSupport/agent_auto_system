import json

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.crews.tasker_apply_crew.crew import TaskerProposalCrew
from src.automation.flows.base import FlowMixin
from src.automation.flows.utils import extract_usage
from src.automation.progress import append_log
from src.automation.tools.tasker_apply_tool import (
    _DEFAULT_TEMPLATE,
    _MIN_CHARGE_FLOOR,
    run_tasker_apply,
)


class TaskerApplyState(BaseModel):
    category_ids: str = ""          # e.g. "110" or "110,101001"
    min_charge: int = 0
    max_charge: int = 0
    proposal_template: str = ""     # optional base/fallback for the LLM writer
    max_cases: int = 5
    dry_run: bool = True            # safety: don't click 送出提案 unless explicitly false
    run_id: int = 0
    usage: dict = {}
    llm_provider: str = ""
    llm_model: str = ""
    previous_error: str = ""


class TaskerApplyFlow(FlowMixin, Flow[TaskerApplyState]):

    @start()
    def validate_payload(self):
        self._check_required("category_ids", "min_charge", "max_charge")
        if self.state.min_charge < _MIN_CHARGE_FLOOR:
            raise ValueError(f"min_charge must be >= {_MIN_CHARGE_FLOOR} (site minimum)")
        if self.state.min_charge > self.state.max_charge:
            raise ValueError("min_charge must be <= max_charge")
        append_log(
            self.state.run_id,
            f"Payload validated — category {self.state.category_ids}, "
            f"{self.state.min_charge}~{self.state.max_charge}, "
            f"max {self.state.max_cases} case(s), dry_run={self.state.dry_run}",
        )
        return self.state.model_dump()

    @listen(validate_payload)
    def execute_apply(self, _):
        template = self.state.proposal_template or _DEFAULT_TEMPLATE

        # Resolve the LLM used to write a tailored 提案說明 per case. If no key /
        # provider is available we fall back to the static template so the run
        # still works without an LLM.
        llm = None
        try:
            from src.automation.harness.provider import resolve as resolve_llm
            llm, _p, _m = resolve_llm(
                self.state.llm_provider or None,
                self.state.llm_model or None,
                temperature=0.5,
            )
        except Exception as exc:  # noqa: BLE001
            append_log(self.state.run_id,
                       f"No LLM available ({exc}); using default proposal template.")

        usage_acc = {"prompt_tokens": 0, "completion_tokens": 0}

        def proposal_fn(title: str, description: str) -> str:
            if llm is None:
                try:
                    return template.format(title=title)
                except Exception:  # noqa: BLE001
                    return template
            try:
                result = TaskerProposalCrew(llm=llm).crew().kickoff(inputs={
                    "case_title": title,
                    "case_description": description,
                    "min_charge": self.state.min_charge,
                    "max_charge": self.state.max_charge,
                    "proposal_template": template,
                    "previous_error": self.state.previous_error,
                })
                u = extract_usage(result)
                usage_acc["prompt_tokens"] += u.get("prompt_tokens", 0)
                usage_acc["completion_tokens"] += u.get("completion_tokens", 0)
                text = result.raw if hasattr(result, "raw") else str(result)
                return (text or "").strip() or template
            except Exception as exc:  # noqa: BLE001 — never fail a case on text-gen
                append_log(self.state.run_id,
                           f"Proposal generation failed ({exc}); using template.")
                try:
                    return template.format(title=title)
                except Exception:  # noqa: BLE001
                    return template

        append_log(self.state.run_id, "Loading tasker.com.tw session and scanning cases...")
        result = run_tasker_apply(
            category_ids=self.state.category_ids,
            min_charge=self.state.min_charge,
            max_charge=self.state.max_charge,
            max_cases=self.state.max_cases,
            dry_run=self.state.dry_run,
            proposal_fn=proposal_fn,
            log=lambda m: append_log(self.state.run_id, m),
        )

        self.state.usage = usage_acc
        append_log(self.state.run_id, "Tasker apply run complete, formatting result...")
        return json.dumps(result, ensure_ascii=False)
