from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task

from src.automation.tools.shopee_scraper_tool import ShopeeSellerScraperTool

_CFG = Path(__file__).parent / "config"

with open(_CFG / "agents.yaml") as _f:
    _AGENTS = yaml.safe_load(_f)
with open(_CFG / "tasks.yaml") as _f:
    _TASKS = yaml.safe_load(_f)


class ShopeeSellerCrew:
    def __init__(self, llm=None):
        self._llm = llm
        self._agents = _AGENTS
        self._tasks = _TASKS

    def crew(self) -> Crew:
        agent = Agent(
            config=self._agents["shopee_seller_analyst"],
            tools=[ShopeeSellerScraperTool()],
            verbose=False,
            llm=self._llm,
        )
        task = Task(config={**self._tasks["shopee_seller_task"], "agent": agent})
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
