import json
import urllib.request
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

_HN_BASE = "https://hacker-news.firebaseio.com/v0"


class HNFetchInput(BaseModel):
    limit: int = Field(default=5, ge=1, le=10)


class HNTopStoriesTool(BaseTool):
    name: str = "hn_top_stories"
    description: str = (
        "Fetch the top stories from Hacker News. "
        "Returns a list of stories with title, url, score, and comment count."
    )
    args_schema: Type[BaseModel] = HNFetchInput

    def _run(self, limit: int = 5) -> list:
        ids_resp = urllib.request.urlopen(f"{_HN_BASE}/topstories.json", timeout=15)
        story_ids = json.loads(ids_resp.read())[:limit]

        stories = []
        for sid in story_ids:
            try:
                item_resp = urllib.request.urlopen(f"{_HN_BASE}/item/{sid}.json", timeout=10)
                item = json.loads(item_resp.read())
                stories.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                    "score": item.get("score", 0),
                    "comments": item.get("descendants", 0),
                    "author": item.get("by", ""),
                })
            except Exception:
                pass
        return stories
