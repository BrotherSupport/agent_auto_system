from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task

_CFG = Path(__file__).parent / "config"

with open(_CFG / "agents.yaml") as _f:
    _AGENTS = yaml.safe_load(_f)
with open(_CFG / "tasks.yaml") as _f:
    _TASKS = yaml.safe_load(_f)


class TaskerRelevanceCrew:
    """Judges whether a single tasker.com.tw case matches the user's task_filter.

    Pure-LLM (no browser tools). This is the "second gate" that runs after the
    category URL filter: the flow calls `.crew().kickoff(...)` once per scanned
    case and skips cases the judge marks irrelevant, BEFORE spending a
    proposal-writing call. Returns a small JSON verdict
    ``{"relevant": bool, "reason": str}``.
    """

    def __init__(self, llm=None):
        self._llm = llm
        self._agents = _AGENTS
        self._tasks = _TASKS

    def crew(self) -> Crew:
        agent = Agent(
            config=self._agents["relevance_judge"],
            verbose=False,
            llm=self._llm,
        )
        task = Task(config={**self._tasks["judge_relevance_task"], "agent": agent})
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
