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
            "role": "Web Content Analyst",
            "goal": "Fetch the content of the given URL and return a comprehensive structured summary — title, key sections, main points, headings, and links.",
            "backstory": "Expert web analyst who extracts and organises page content clearly. Always bases output strictly on what the scraper tool returns. Produces clean, structured JSON output.",
            "tools": ["web_scraper"],
            "crew": "WebScraperCrew",
            "task": "scrape_task",
            "job_type": "web_scraper",
            "source_file": "src/automation/crews/web_scraper_crew/config/agents.yaml",
        },
        {
            "id": "email_sender_agent",
            "name": "Email Sender Agent",
            "role": "Email Delivery Agent",
            "goal": "Send emails exactly as instructed using the gmail_send_email tool. Never modify subject, body, or recipients.",
            "backstory": "Reliable email dispatch agent. Receives ready-to-send email parameters and calls the Gmail send tool once with those exact parameters without altering content.",
            "tools": ["gmail_send_email"],
            "crew": "EmailSenderCrew",
            "task": "send_email_task",
            "job_type": "email_sender",
            "source_file": "src/automation/crews/email_sender_crew/config/agents.yaml",
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
            "description": "Fetch a web page and return full structured content: title, meta description, h1-h3 headings, main text (up to 8 000 chars), outbound links, and word count.",
            "inputs": [
                {"name": "url", "type": "str", "description": "URL to fetch"},
            ],
            "used_by": ["WebScraperCrew"],
            "source_file": "src/automation/tools/web_scraper_tool.py",
        },
        {
            "id": "gmail_send_email",
            "name": "Gmail Send",
            "class": "GmailSendTool",
            "description": "Send an email via Gmail SMTP using an app password. Supports multiple recipients (comma-separated), CC, and HTML or plain-text bodies.",
            "inputs": [
                {"name": "to",      "type": "str",           "description": "Recipient(s), comma-separated"},
                {"name": "subject", "type": "str",           "description": "Email subject line"},
                {"name": "body",    "type": "str",           "description": "HTML or plain-text email body"},
                {"name": "cc",      "type": "str (optional)","description": "CC recipients, comma-separated"},
            ],
            "used_by": ["EmailSenderCrew"],
            "source_file": "src/automation/tools/gmail_send_tool.py",
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
                    "description": "Fetch the URL and extract a comprehensive structured summary of all page content.",
                    "expected_output": '{"url": "...", "title": "...", "summary": "...", "key_points": [...], "headings": [...], "word_count": N, "links": [...]}',
                    "config_file": "src/automation/crews/web_scraper_crew/config/tasks.yaml",
                }
            ],
            "source_file": "src/automation/crews/web_scraper_crew/crew.py",
        },
        {
            "id": "email_sender_crew",
            "name": "EmailSenderCrew",
            "process": "sequential",
            "agents": ["email_sender_agent"],
            "job_type": "email_sender",
            "flow": "EmailSenderFlow",
            "tasks": [
                {
                    "name": "send_email_task",
                    "description": "Call gmail_send_email tool with the exact provided parameters without modification.",
                    "expected_output": '{"sent": true, "to": "...", "subject": "...", "confirmation": "..."}',
                    "config_file": "src/automation/crews/email_sender_crew/config/tasks.yaml",
                }
            ],
            "source_file": "src/automation/crews/email_sender_crew/crew.py",
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
                    "description": "Kicks off WebScraperCrew with the url. Returns structured page summary JSON.",
                },
            ],
            "source_file": "src/automation/flows/web_scraper_flow.py",
        },
        {
            "id": "email_sender_flow",
            "name": "EmailSenderFlow",
            "job_type": "email_sender",
            "crew": "EmailSenderCrew (direct tool call — no LLM)",
            "state_fields": [
                {"name": "to",      "type": "str", "default": ""},
                {"name": "subject", "type": "str", "default": ""},
                {"name": "body",    "type": "str", "default": ""},
                {"name": "cc",      "type": "str", "default": ""},
                {"name": "run_id",  "type": "int", "default": 0},
            ],
            "steps": [
                {
                    "name": "validate_payload",
                    "decorator": "@start()",
                    "description": "Validates to, subject, and body are present. Logs recipient count.",
                },
                {
                    "name": "send_email",
                    "decorator": "@listen(validate_payload)",
                    "description": "Calls GmailSendTool directly via SMTP — no LLM involved. Returns send confirmation JSON.",
                },
            ],
            "source_file": "src/automation/flows/email_sender_flow.py",
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
