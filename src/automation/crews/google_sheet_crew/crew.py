from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task

from src.automation.tools.google_sheet_tool import GoogleSheetTool

_CFG = Path(__file__).parent / "config"

with open(_CFG / "agents.yaml") as _f:
    _AGENTS = yaml.safe_load(_f)
with open(_CFG / "tasks.yaml") as _f:
    _TASKS = yaml.safe_load(_f)


class GoogleSheetCrew:
    def __init__(self, llm=None):
        self._llm = llm

    def crew(self) -> Crew:
        agent = Agent(
            config=_AGENTS["google_sheet_agent"],
            tools=[GoogleSheetTool()],
            verbose=False,
            llm=self._llm,
        )
        task = Task(config={**_TASKS["sheet_read_task"], "agent": agent})
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
