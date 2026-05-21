from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from src.automation.tools.hn_tool import HNTopStoriesTool


@CrewBase
class HNDigestCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"
    llm = None  # set by flow before crew() is called

    @agent
    def hn_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["hn_analyst"],
            tools=[HNTopStoriesTool()],
            verbose=False,
            llm=self.llm,
        )

    @task
    def digest_task(self) -> Task:
        return Task(config=self.tasks_config["digest_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )
