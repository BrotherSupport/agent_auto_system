import yaml
from pathlib import Path

from crewai import Agent, Crew, Process, Task

from src.automation.tools.x_scraper_tool import XScraperTool

_CFG = Path(__file__).parent / "config"


class XScraperCrew:
    def __init__(self, llm=None):
        self._llm = llm
        with open(_CFG / "agents.yaml") as f:
            self._agents = yaml.safe_load(f)
        with open(_CFG / "tasks.yaml") as f:
            self._tasks = yaml.safe_load(f)

    def crew(self) -> Crew:
        agent = Agent(
            config=self._agents["x_analyst"],
            tools=[XScraperTool()],
            verbose=False,
            llm=self._llm,
        )
        task = Task(config={**self._tasks["x_scrape_task"], "agent": agent})
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
