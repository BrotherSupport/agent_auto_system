import yaml
from pathlib import Path

from crewai import Agent, Crew, Process, Task

from src.automation.tools.hn_tool import HNTopStoriesTool

_CFG = Path(__file__).parent / "config"

with open(_CFG / "agents.yaml") as _f:
    _AGENTS = yaml.safe_load(_f)
with open(_CFG / "tasks.yaml") as _f:
    _TASKS = yaml.safe_load(_f)


class HNDigestCrew:
    def __init__(self, llm=None):
        self._llm = llm
        self._agents = _AGENTS
        self._tasks = _TASKS

    def crew(self) -> Crew:
        analyst = Agent(
            config=self._agents["hn_analyst"],
            tools=[HNTopStoriesTool()],
            verbose=False,
            llm=self._llm,
        )
        task = Task(config={**self._tasks["digest_task"], "agent": analyst})
        return Crew(
            agents=[analyst],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
