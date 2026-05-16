import re
import urllib.request
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


class ScrapeInput(BaseModel):
    url: str


class WebScraperTool(BaseTool):
    name: str = "web_scraper"
    description: str = (
        "Fetch a web page and return its title and main text content. "
        "Use this to read page content before answering questions about it."
    )
    args_schema: Type[BaseModel] = ScrapeInput

    def _run(self, url: str) -> dict:
        req = urllib.request.Request(url, headers=_HEADERS)
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")

        title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
        title = title_m.group(1).strip() if title_m else "Untitled"

        html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.I)
        html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.I)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()

        return {"title": title, "text": text[:8000]}
