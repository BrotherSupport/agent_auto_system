import yaml
from pathlib import Path

from crewai import Agent, Crew, Process, Task

from src.automation.tools.hn_tool import HNTopStoriesTool

_CFG = Path(__file__).parent / "config"


class HNDigestCrew:
    def __init__(self, llm=None):
        self._llm = llm
        with open(_CFG / "agents.yaml") as f:
            self._agents = yaml.safe_load(f)
        with open(_CFG / "tasks.yaml") as f:
            self._tasks = yaml.safe_load(f)

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
