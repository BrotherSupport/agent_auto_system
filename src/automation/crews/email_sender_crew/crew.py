from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task

from src.automation.tools.gmail_send_tool import GmailSendTool

_CFG = Path(__file__).parent / "config"

with open(_CFG / "agents.yaml") as _f:
    _AGENTS = yaml.safe_load(_f)
with open(_CFG / "tasks.yaml") as _f:
    _TASKS = yaml.safe_load(_f)


class EmailSenderCrew:
    def __init__(self, llm=None):
        self._llm = llm
        self._agents = _AGENTS
        self._tasks = _TASKS

    def crew(self) -> Crew:
        agent = Agent(
            config=self._agents["email_sender_agent"],
            tools=[GmailSendTool()],
            verbose=False,
            llm=self._llm,
        )
        task = Task(config={**self._tasks["send_email_task"], "agent": agent})
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
