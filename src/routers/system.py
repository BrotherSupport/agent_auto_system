from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _read_file(rel: str) -> str:
    try:
        return (_PROJECT_ROOT / rel).read_text(encoding="utf-8")
    except Exception:
        return ""


_CATALOG: dict = {
    "agents": [
        {
            "id": "form_agent",
            "name": "Form Agent",
            "role": "Web Form Automation Specialist",
            "goal": "Accurately fill and submit the AI Consultant Google Form with the provided company information.",
            "backstory": "Expert at web form automation. Uses browser tools to navigate forms, fill fields precisely, and confirm successful submission.",
            "tools": ["google_form_inspector", "google_form_submit"],
            "crew": "FormFillerCrew",
            "task": "fill_form_task",
            "job_type": "google_form_fill",
            "source_file": "src/automation/crews/form_crew/config/agents.yaml",
        },
        {
            "id": "web_scraper_agent",
            "name": "Web Scraper Agent",
            "role": "Web Research Analyst",
            "goal": "Fetch the content of the given URL and provide a thorough, accurate answer to the user's question based solely on what you find on the page.",
            "backstory": "Expert at reading web pages and extracting key information. Always bases answers on what's actually read. Produces clean, structured JSON output.",
            "tools": ["web_scraper"],
            "crew": "WebScraperCrew",
            "task": "scrape_task",
            "job_type": "web_scraper",
            "source_file": "src/automation/crews/web_scraper_crew/config/agents.yaml",
        },
        {
            "id": "hn_analyst",
            "name": "HN Analyst",
            "role": "Tech News Analyst",
            "goal": "Fetch the top Hacker News stories and write a crisp, useful digest that highlights the most interesting developments in tech.",
            "backstory": "Senior technology journalist who reads Hacker News daily. Talent for spotting patterns, summarizing complex topics, and highlighting what matters most to developers and founders.",
            "tools": ["hn_top_stories"],
            "crew": "HNDigestCrew",
            "task": "digest_task",
            "job_type": "hacker_news_digest",
            "source_file": "src/automation/crews/hn_digest_crew/config/agents.yaml",
        },
        {
            "id": "x_analyst",
            "name": "X Analyst",
            "role": "Social Media Intelligence Analyst",
            "goal": "Fetch and analyze recent posts from a given X (Twitter) user profile, identify recurring themes, and surface the most engaging content.",
            "backstory": "Sharp social media analyst specializing in extracting signal from noise. Reads post data carefully, spots patterns, and summarizes in a crisp, factual way.",
            "tools": ["x_post_scraper"],
            "crew": "XScraperCrew",
            "task": "x_scrape_task",
            "job_type": "x_scraper",
            "source_file": "src/automation/crews/x_scraper_crew/config/agents.yaml",
        },
    ],
    "tools": [
        {
            "id": "google_form_inspector",
            "name": "Google Form Inspector",
            "class": "GoogleFormInspectorTool",
            "description": "Fetch a Google Form's structure. Returns the form_id and for each question: title, entry_id, type, and options. Call this FIRST before submitting.",
            "inputs": [
                {"name": "url", "type": "str", "description": "The Google Form URL"},
            ],
            "used_by": ["FormFillerCrew"],
            "source_file": "src/automation/tools/google_form_tools.py",
        },
        {
            "id": "google_form_submit",
            "name": "Google Form Submit",
            "class": "GoogleFormSubmitTool",
            "description": "Submit a Google Form via HTTP POST with session cookies and CSRF token. Handles the full GET→POST flow to avoid silent field discards.",
            "inputs": [
                {"name": "form_id", "type": "str", "description": "Form ID from URL"},
                {"name": "responses", "type": "dict", "description": "Mapping of entry_id → answer value"},
            ],
            "used_by": ["FormFillerCrew"],
            "source_file": "src/automation/tools/google_form_tools.py",
        },
        {
            "id": "web_scraper",
            "name": "Web Scraper",
            "class": "WebScraperTool",
            "description": "Fetch a web page and return its title and main text content (up to 8 000 chars, scripts/styles stripped).",
            "inputs": [
                {"name": "url", "type": "str", "description": "URL to fetch"},
            ],
            "used_by": ["WebScraperCrew"],
            "source_file": "src/automation/tools/web_scraper_tool.py",
        },
        {
            "id": "hn_top_stories",
            "name": "HN Top Stories",
            "class": "HNTopStoriesTool",
            "description": "Fetch the top stories from Hacker News via Firebase API. Returns title, url, score, comments, and author for each story.",
            "inputs": [
                {"name": "limit", "type": "int", "description": "Number of stories to fetch (1–10)"},
            ],
            "used_by": ["HNDigestCrew"],
            "source_file": "src/automation/tools/hn_tool.py",
        },
        {
            "id": "x_post_scraper",
            "name": "X Post Scraper",
            "class": "XScraperTool",
            "description": "Fetch recent posts from a public X profile. Tries multiple nitter instances first, falls back to Playwright on x.com.",
            "inputs": [
                {"name": "username", "type": "str", "description": "X handle (without @)"},
                {"name": "limit", "type": "int", "description": "Number of posts to fetch"},
            ],
            "used_by": ["XScraperCrew"],
            "source_file": "src/automation/tools/x_scraper_tool.py",
        },
    ],
    "crews": [
        {
            "id": "form_filler_crew",
            "name": "FormFillerCrew",
            "process": "sequential",
            "agents": ["form_agent"],
            "job_type": "google_form_fill",
            "flow": "FormFillFlow",
            "tasks": [
                {
                    "name": "fill_form_task",
                    "description": "Inspect the Google Form structure then submit with provided company details.",
                    "expected_output": '{"submitted": true, "confirmation": "..."}',
                    "config_file": "src/automation/crews/form_crew/config/tasks.yaml",
                }
            ],
            "source_file": "src/automation/crews/form_crew/crew.py",
        },
        {
            "id": "web_scraper_crew",
            "name": "WebScraperCrew",
            "process": "sequential",
            "agents": ["web_scraper_agent"],
            "job_type": "web_scraper",
            "flow": "WebScraperFlow",
            "tasks": [
                {
                    "name": "scrape_task",
                    "description": "Fetch the URL content and answer the user's question strictly from the page.",
                    "expected_output": '{"title": "...", "answer": "...", "key_points": [...]}',
                    "config_file": "src/automation/crews/web_scraper_crew/config/tasks.yaml",
                }
            ],
            "source_file": "src/automation/crews/web_scraper_crew/crew.py",
        },
        {
            "id": "hn_digest_crew",
            "name": "HNDigestCrew",
            "process": "sequential",
            "agents": ["hn_analyst"],
            "job_type": "hacker_news_digest",
            "flow": "HNDigestFlow",
            "tasks": [
                {
                    "name": "digest_task",
                    "description": "Fetch top N HN stories, summarize each, pick story of the day, identify 2–3 themes.",
                    "expected_output": '{"story_of_the_day": {...}, "stories": [...], "themes": [...]}',
                    "config_file": "src/automation/crews/hn_digest_crew/config/tasks.yaml",
                }
            ],
            "source_file": "src/automation/crews/hn_digest_crew/crew.py",
        },
        {
            "id": "x_scraper_crew",
            "name": "XScraperCrew",
            "process": "sequential",
            "agents": ["x_analyst"],
            "job_type": "x_scraper",
            "flow": "XScraperFlow",
            "tasks": [
                {
                    "name": "x_scrape_task",
                    "description": "Fetch N posts from a public X profile, find top post, identify themes, write summary.",
                    "expected_output": '{"username": "...", "post_count": N, "top_post": {...}, "themes": [...], "summary": "...", "posts": [...]}',
                    "config_file": "src/automation/crews/x_scraper_crew/config/tasks.yaml",
                }
            ],
            "source_file": "src/automation/crews/x_scraper_crew/crew.py",
        },
    ],
    "workflows": [
        {
            "id": "form_fill_flow",
            "name": "FormFillFlow",
            "job_type": "google_form_fill",
            "crew": "FormFillerCrew",
            "state_fields": [
                {"name": "company_name", "type": "str", "default": ""},
                {"name": "company_size", "type": "str", "default": ""},
                {"name": "ai_problem", "type": "str", "default": ""},
                {"name": "run_id", "type": "int", "default": 0},
            ],
            "steps": [
                {
                    "name": "validate_payload",
                    "decorator": "@start()",
                    "description": "Validates all required fields (company_name, company_size, ai_problem) are present. Raises ValueError if any are missing.",
                },
                {
                    "name": "execute_crew",
                    "decorator": "@listen(validate_payload)",
                    "description": "Kicks off FormFillerCrew with the validated payload. Returns the raw crew output.",
                },
            ],
            "source_file": "src/automation/flows/form_fill_flow.py",
        },
        {
            "id": "web_scraper_flow",
            "name": "WebScraperFlow",
            "job_type": "web_scraper",
            "crew": "WebScraperCrew",
            "state_fields": [
                {"name": "url", "type": "str", "default": ""},
                {"name": "question", "type": "str", "default": "What is this page about?"},
                {"name": "run_id", "type": "int", "default": 0},
            ],
            "steps": [
                {
                    "name": "validate_payload",
                    "decorator": "@start()",
                    "description": "Validates that url is present. Raises ValueError if missing.",
                },
                {
                    "name": "execute_crew",
                    "decorator": "@listen(validate_payload)",
                    "description": "Kicks off WebScraperCrew with url and question. Returns the raw crew output.",
                },
            ],
            "source_file": "src/automation/flows/web_scraper_flow.py",
        },
        {
            "id": "hn_digest_flow",
            "name": "HNDigestFlow",
            "job_type": "hacker_news_digest",
            "crew": "HNDigestCrew",
            "state_fields": [
                {"name": "limit", "type": "int", "default": 5},
                {"name": "run_id", "type": "int", "default": 0},
            ],
            "steps": [
                {
                    "name": "validate_payload",
                    "decorator": "@start()",
                    "description": "Validates that limit is between 1 and 10.",
                },
                {
                    "name": "execute_crew",
                    "decorator": "@listen(validate_payload)",
                    "description": "Kicks off HNDigestCrew with the limit. Returns the digest JSON.",
                },
            ],
            "source_file": "src/automation/flows/hn_digest_flow.py",
        },
        {
            "id": "x_scraper_flow",
            "name": "XScraperFlow",
            "job_type": "x_scraper",
            "crew": "XScraperCrew",
            "state_fields": [
                {"name": "username", "type": "str", "default": ""},
                {"name": "limit", "type": "int", "default": 5},
                {"name": "run_id", "type": "int", "default": 0},
            ],
            "steps": [
                {
                    "name": "validate_payload",
                    "decorator": "@start()",
                    "description": "Validates that username is present. Raises ValueError if missing.",
                },
                {
                    "name": "execute_crew",
                    "decorator": "@listen(validate_payload)",
                    "description": "Kicks off XScraperCrew with username and limit. Returns the social media analysis JSON.",
                },
            ],
            "source_file": "src/automation/flows/x_scraper_flow.py",
        },
    ],
}


@router.get("/system")
def get_system():
    result: dict = {}
    seen_files: dict[str, str] = {}

    for category, items in _CATALOG.items():
        enriched = []
        for item in items:
            item = dict(item)
            sf = item.get("source_file")
            if sf:
                if sf not in seen_files:
                    seen_files[sf] = _read_file(sf)
                item["source_code"] = seen_files[sf]
            if category == "crews":
                tasks = []
                for t in item.get("tasks", []):
                    t = dict(t)
                    cf = t.get("config_file")
                    if cf:
                        if cf not in seen_files:
                            seen_files[cf] = _read_file(cf)
                        t["config_code"] = seen_files[cf]
                    tasks.append(t)
                item["tasks"] = tasks
            enriched.append(item)
        result[category] = enriched

    return result
