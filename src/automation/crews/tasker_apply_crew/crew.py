from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task

_CFG = Path(__file__).parent / "config"

with open(_CFG / "agents.yaml") as _f:
    _AGENTS = yaml.safe_load(_f)
with open(_CFG / "tasks.yaml") as _f:
    _TASKS = yaml.safe_load(_f)


class TaskerProposalCrew:
    """Writes a tailored 提案說明 for a single tasker.com.tw case.

    Pure-LLM (no browser tools). The flow calls `.crew().kickoff(...)` once per
    case; the browser automation itself lives in tasker_apply_tool.
    """

    def __init__(self, llm=None):
        self._llm = llm
        self._agents = _AGENTS
        self._tasks = _TASKS

    def crew(self) -> Crew:
        agent = Agent(
            config=self._agents["proposal_writer"],
            verbose=False,
            llm=self._llm,
        )
        task = Task(config={**self._tasks["write_proposal_task"], "agent": agent})
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
