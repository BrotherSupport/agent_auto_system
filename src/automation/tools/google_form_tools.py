"""
Two-tool approach for Google Form submission:
  1. GoogleFormInspectorTool  – GET form HTML, parse structure → question titles + entry IDs
  2. GoogleFormSubmitTool     – POST entry.ID=value to formResponse URL

No browser or OAuth required for public forms.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}
_TYPE_MAP = {0: "short_answer", 1: "paragraph", 2: "radio", 3: "checkbox", 4: "dropdown"}


# ── Inspector ──────────────────────────────────────────────────────────────────

class InspectInput(BaseModel):
    url: str


class GoogleFormInspectorTool(BaseTool):
    name: str = "google_form_inspector"
    description: str = (
        "Fetch a Google Form's structure. Returns the form_id, and for each question: "
        "title, entry_id, type (short_answer | paragraph | radio | dropdown), and options "
        "for radio/dropdown. Call this FIRST to discover entry IDs before submitting."
    )
    args_schema: Type[BaseModel] = InspectInput

    def _run(self, url: str) -> dict:
        html = _fetch_html(url)
        return {
            "form_id": _extract_form_id(url),
            "questions": _parse_questions(html),
        }


# ── Submit ─────────────────────────────────────────────────────────────────────

class SubmitInput(BaseModel):
    form_id: str
    responses: dict  # {"entry_id_digits": "answer_value"}


class GoogleFormSubmitTool(BaseTool):
    name: str = "google_form_submit"
    description: str = (
        "Submit a Google Form via HTTP POST. "
        "Pass form_id (from the form URL) and responses: a dict mapping "
        "entry_id (digits only, no 'entry.' prefix) to the answer string. "
        "For radio questions the value must exactly match one of the listed options."
    )
    args_schema: Type[BaseModel] = SubmitInput

    def _run(self, form_id: str, responses: dict) -> dict:
        submit_url = f"https://docs.google.com/forms/d/e/{form_id}/formResponse"

        post_data: dict[str, str] = {}
        for entry_id, value in responses.items():
            key = f"entry.{entry_id}"
            if str(value) == "其他":
                post_data[key] = "__other_option__"
            else:
                post_data[key] = str(value)

        encoded = urllib.parse.urlencode(post_data, encoding="utf-8").encode("utf-8")
        req = urllib.request.Request(
            submit_url,
            data=encoded,
            headers={
                **_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://docs.google.com",
                "Referer": f"https://docs.google.com/forms/d/e/{form_id}/viewform",
            },
            method="POST",
        )

        try:
            resp = urllib.request.urlopen(req, timeout=30)
            final_url = resp.geturl()
            body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            final_url = submit_url
            body = exc.read().decode("utf-8", errors="replace")

        success = "formResponse" in final_url or "freebirdFormviewerView" in body
        return {
            "submitted": success,
            "final_url": final_url,
            "confirmation": "Response recorded successfully" if success else "Submission may have failed — check final_url",
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8")


def _extract_form_id(url: str) -> str:
    m = re.search(r"/forms/d/e/([^/?#]+)", url)
    return m.group(1) if m else url


def _parse_questions(html: str) -> list[dict]:
    m = re.search(r"FB_PUBLIC_LOAD_DATA_ = (\[.*?\]);\s*</script>", html, re.DOTALL)
    if not m:
        raise ValueError("Could not extract form structure — FB_PUBLIC_LOAD_DATA_ not found")

    data = json.loads(m.group(1))
    items = data[1][1]
    questions = []

    for item in items:
        title = item[1]
        qtype_raw = item[3]
        entry_data_list = item[4]
        if not entry_data_list:
            continue

        entry_data = entry_data_list[0]
        entry_id = str(entry_data[0])
        options_raw = entry_data[1] or []
        # skip empty-string option (the "other" sentinel)
        options = [o[0] for o in options_raw if o[0]]

        q: dict = {
            "title": title,
            "entry_id": entry_id,
            "type": _TYPE_MAP.get(qtype_raw, "unknown"),
        }
        if options:
            q["options"] = options
        questions.append(q)

    return questions
