from typing import Literal, Type

from crewai.tools import BaseTool
from playwright.sync_api import sync_playwright
from pydantic import BaseModel

FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSc0E2-jTMy8WNFLlHc5rG4zw3U1QaCykBra3mdqFv0DNb8i9Q/viewform"


class FormInput(BaseModel):
    url: str = FORM_URL
    company_name: str
    company_size: Literal["0-10", "11-100", "200 up", "其他"]
    ai_problem: str


class PlaywrightFormTool(BaseTool):
    name: str = "playwright_form_tool"
    description: str = (
        "Fill and submit the AI Consultant Google Form. "
        "Args: url, company_name, company_size (0-10 | 11-100 | 200 up | 其他), ai_problem."
    )
    args_schema: Type[BaseModel] = FormInput

    def _run(
        self,
        url: str = FORM_URL,
        company_name: str = "",
        company_size: str = "0-10",
        ai_problem: str = "",
    ) -> dict:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle")

            # Q1: 公司名稱 — first short-answer text input
            page.locator('input[type="text"]').nth(0).fill(company_name)

            # Q2: 公司規模 — radio button matched by visible text
            page.locator(f'div[role="radio"]:has-text("{company_size}")').first.click()

            # Q3: 想用AI解決的問題 — second text input or first textarea
            text_inputs = page.locator('input[type="text"]').all()
            if len(text_inputs) >= 2:
                page.locator('input[type="text"]').nth(1).fill(ai_problem)
            else:
                page.locator("textarea").first.fill(ai_problem)

            # Submit (Google Forms uses div[role="button"] for submit)
            page.locator('div[role="button"]:has-text("提交"), div[role="button"]:has-text("Submit")').first.click()
            page.wait_for_timeout(2000)

            confirmation = "Form submitted"
            try:
                el = page.locator(".freebirdFormviewerViewResponseConfirmationMessage")
                if el.count() > 0:
                    confirmation = el.first.text_content() or confirmation
            except Exception:
                pass

            browser.close()

        return {"submitted": True, "confirmation_text": confirmation.strip()}
