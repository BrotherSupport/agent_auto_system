from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from src.automation.tools.playwright_form_tool import PlaywrightFormTool


@CrewBase
class FormFillerCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def form_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["form_agent"],
            tools=[PlaywrightFormTool()],
            verbose=False,
        )

    @task
    def fill_form_task(self) -> Task:
        return Task(config=self.tasks_config["fill_form_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )
