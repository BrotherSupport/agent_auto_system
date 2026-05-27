from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task

from src.automation.tools.google_form_tools import GoogleFormInspectorTool, GoogleFormSubmitTool

_CFG = Path(__file__).parent / "config"

with open(_CFG / "agents.yaml") as _f:
    _AGENTS = yaml.safe_load(_f)
with open(_CFG / "tasks.yaml") as _f:
    _TASKS = yaml.safe_load(_f)


class FormFillerCrew:
    def __init__(self, llm=None):
        self._llm = llm
        self._agents = _AGENTS
        self._tasks = _TASKS

    def crew(self) -> Crew:
        agent = Agent(
            config=self._agents["form_agent"],
            tools=[GoogleFormInspectorTool(), GoogleFormSubmitTool()],
            verbose=False,
            llm=self._llm,
        )
        task = Task(config={**self._tasks["fill_form_task"], "agent": agent})
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
