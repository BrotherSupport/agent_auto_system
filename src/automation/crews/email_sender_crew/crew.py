import yaml
from pathlib import Path

from crewai import Agent, Crew, Process, Task

from src.automation.tools.gmail_send_tool import GmailSendTool

_CFG = Path(__file__).parent / "config"


class EmailSenderCrew:
    def __init__(self, llm=None):
        self._llm = llm
        with open(_CFG / "agents.yaml") as f:
            self._agents = yaml.safe_load(f)
        with open(_CFG / "tasks.yaml") as f:
            self._tasks = yaml.safe_load(f)

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
