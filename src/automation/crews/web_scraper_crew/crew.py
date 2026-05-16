from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from src.automation.tools.web_scraper_tool import WebScraperTool


@CrewBase
class WebScraperCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def web_scraper_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["web_scraper_agent"],
            tools=[WebScraperTool()],
            verbose=False,
        )

    @task
    def scrape_task(self) -> Task:
        return Task(config=self.tasks_config["scrape_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )
