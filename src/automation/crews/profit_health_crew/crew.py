from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task

from src.automation.progress import append_log
from src.automation.tools.profit_calc_tool import ProfitCalcTool

_CFG = Path(__file__).parent / "config"

with open(_CFG / "agents.yaml") as _f:
    _AGENTS = yaml.safe_load(_f)
with open(_CFG / "tasks.yaml") as _f:
    _TASKS = yaml.safe_load(_f)


class ProfitHealthCrew:
    """Sequential crew: 驗證 → 修正 → 分析 → 建議.

    Only the analyzer holds the profit_calc tool — all arithmetic stays
    deterministic. Plain class (no @CrewBase); LLM injected via constructor.
    """

    def __init__(self, llm=None, run_id=None):
        self._llm = llm
        self._run_id = run_id

    def crew(self) -> Crew:
        validator = Agent(config=_AGENTS["data_validator"], verbose=False, llm=self._llm)
        corrector = Agent(config=_AGENTS["data_corrector"], verbose=False, llm=self._llm)
        analyzer = Agent(
            config=_AGENTS["profit_analyzer"],
            tools=[ProfitCalcTool()],
            verbose=False,
            llm=self._llm,
        )
        advisor = Agent(config=_AGENTS["action_advisor"], verbose=False, llm=self._llm)

        t_validate = Task(config={**_TASKS["validate_task"], "agent": validator})
        t_correct = Task(config={**_TASKS["correct_task"], "agent": corrector},
                         context=[t_validate])
        t_analyze = Task(config={**_TASKS["analyze_task"], "agent": analyzer},
                         context=[t_correct])
        t_advise = Task(config={**_TASKS["advise_task"], "agent": advisor},
                        context=[t_validate, t_analyze])

        kwargs = {}
        if self._run_id is not None:
            run_id = self._run_id

            def _on_task(output):
                # Emit a per-agent progress log so the run page can light up each node.
                role = getattr(output, "agent", "") or ""
                append_log(run_id, f"{role} 完成")

            kwargs["task_callback"] = _on_task

        return Crew(
            agents=[validator, corrector, analyzer, advisor],
            tasks=[t_validate, t_correct, t_analyze, t_advise],
            process=Process.sequential,
            verbose=False,
            **kwargs,
        )
