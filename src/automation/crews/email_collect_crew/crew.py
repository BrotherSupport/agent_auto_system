from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task

_CFG = Path(__file__).parent / "config"

with open(_CFG / "agents.yaml") as _f:
    _AGENTS = yaml.safe_load(_f)
with open(_CFG / "tasks.yaml") as _f:
    _TASKS = yaml.safe_load(_f)


class EmailCollectCrew:
    """Qualifies discovered businesses (ICP fit + personalization hook).

    Pure reasoning over the JSON list the flow passes in — no tools; the funnel's
    discovery / extraction / verification is done deterministically in the flow.
    """

    def __init__(self, llm=None):
        self._llm = llm
        self._agents = _AGENTS
        self._tasks = _TASKS

    def crew(self) -> Crew:
        agent = Agent(
            config=self._agents["lead_qualifier_agent"],
            verbose=False,
            llm=self._llm,
        )
        task = Task(config={**self._tasks["qualify_task"], "agent": agent})
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
