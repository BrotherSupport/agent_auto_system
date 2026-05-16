"""
Scrape recent posts from a public X (Twitter) profile.
Strategy: try multiple nitter instances (plain HTTP), then fall back to
Playwright on x.com which can extract posts before login walls appear.
"""
import html as _html_mod
import http.cookiejar
import json
import re
import urllib.error
import urllib.request
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_NITTER_INSTANCES = [
    "https://nitter.tux.pizza",
    "https://nitter.cz",
    "https://nitter.rawbit.ninja",
    "https://n.opnxng.com",
    "https://nitter.privacyredirect.com",
    "https://xcancel.com",
]


class XScrapeInput(BaseModel):
    username: str
    limit: int = 5


class XScraperTool(BaseTool):
    name: str = "x_post_scraper"
    description: str = (
        "Fetch recent posts from a public X (Twitter) user profile. "
        "Returns post text, date, likes, and retweets for each post."
    )
    args_schema: Type[BaseModel] = XScrapeInput

    def _run(self, username: str, limit: int = 5) -> dict:
        handle = username.lstrip("@")
        errors: list[str] = []

        # 1. Try nitter instances
        for base in _NITTER_INSTANCES:
            try:
                jar = http.cookiejar.CookieJar()
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
                url = f"{base}/{handle}"
                req = urllib.request.Request(url, headers=_HEADERS)
                resp = opener.open(req, timeout=15)
                html = resp.read().decode("utf-8", errors="replace")

                if "bot" in html[:500].lower() or "captcha" in html[:500].lower():
                    errors.append(f"{base}: bot-detection page")
                    continue

                posts = _parse_nitter_posts(html, limit)
                if posts:
                    return {"username": handle, "source": base, "posts": posts}
                errors.append(f"{base}: no posts found in HTML")
            except urllib.error.HTTPError as e:
                errors.append(f"{base}: HTTP {e.code}")
            except Exception as e:
                errors.append(f"{base}: {type(e).__name__}: {e}")

        # 2. Playwright fallback on x.com
        try:
            posts = _scrape_with_playwright(handle, limit)
            if posts:
                return {"username": handle, "source": "x.com (playwright)", "posts": posts}
            errors.append("playwright: no articles found (login wall likely)")
        except Exception as e:
            errors.append(f"playwright: {type(e).__name__}: {e}")

        return {
            "username": handle,
            "posts": [],
            "error": "Could not fetch posts — " + " | ".join(errors[:4]),
        }


# ── nitter HTML parsing ────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _stat(chunk: str, icon_class: str) -> int:
    m = re.search(rf'class="{icon_class}".*?<span[^>]*>([0-9,]+)</span>', chunk, re.DOTALL)
    return int(m.group(1).replace(",", "")) if m else 0


def _parse_nitter_posts(html: str, limit: int) -> list[dict]:
    posts: list[dict] = []
    chunks = re.split(r'<div class="timeline-item\b', html)[1:]

    for chunk in chunks:
        if re.search(r'class="[^"]*retweet[^"]*"', chunk[:300]):
            continue
        content_m = re.search(r'class="tweet-content[^"]*"[^>]*>(.*?)</div>', chunk, re.DOTALL)
        if not content_m:
            continue
        text = _clean(content_m.group(1))
        if not text:
            continue
        date_m = re.search(r'title="([^"]+)"[^>]*>\s*(?:\d|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', chunk)
        date = date_m.group(1) if date_m else ""
        posts.append({
            "text": text[:500],
            "date": date,
            "likes": _stat(chunk, "icon-heart"),
            "retweets": _stat(chunk, "icon-retweet"),
            "replies": _stat(chunk, "icon-comment"),
        })
        if len(posts) >= limit:
            break
    return posts


# ── Playwright fallback ────────────────────────────────────────────────────────

def _scrape_with_playwright(handle: str, limit: int) -> list[dict]:
    from playwright.sync_api import sync_playwright

    posts: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=_HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = ctx.new_page()
        # Block heavy media to speed up initial render
        page.route("**/*.{png,jpg,jpeg,gif,mp4,webm,svg}", lambda r: r.abort())

        try:
            page.goto(f"https://x.com/{handle}", timeout=25000, wait_until="domcontentloaded")
            # Let JS render the timeline before any modal blocks it
            page.wait_for_timeout(3500)

            articles = page.locator('article[data-testid="tweet"]').all()
            for article in articles[:limit]:
                try:
                    text_loc = article.locator('[data-testid="tweetText"]').first
                    text = text_loc.inner_text(timeout=2000) if text_loc.count() else ""
                    time_loc = article.locator("time").first
                    date = time_loc.get_attribute("datetime", timeout=2000) if time_loc.count() else ""
                    if text:
                        posts.append({"text": text, "date": date or "", "likes": 0, "retweets": 0, "replies": 0})
                except Exception:
                    pass
        finally:
            browser.close()

    return posts
