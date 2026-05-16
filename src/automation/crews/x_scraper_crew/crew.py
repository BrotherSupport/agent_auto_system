from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from src.automation.tools.x_scraper_tool import XScraperTool


@CrewBase
class XScraperCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def x_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["x_analyst"],
            tools=[XScraperTool()],
            verbose=False,
        )

    @task
    def x_scrape_task(self) -> Task:
        return Task(config=self.tasks_config["x_scrape_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )
