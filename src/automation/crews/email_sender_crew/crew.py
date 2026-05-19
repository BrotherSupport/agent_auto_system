from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from src.automation.tools.gmail_send_tool import GmailSendTool


@CrewBase
class EmailSenderCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def email_sender_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["email_sender_agent"],
            tools=[GmailSendTool()],
            verbose=False,
        )

    @task
    def send_email_task(self) -> Task:
        return Task(config=self.tasks_config["send_email_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )
