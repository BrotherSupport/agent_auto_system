"""
Scrape recent posts from a public X (Twitter) profile.
Strategy: try multiple nitter instances (plain HTTP), then fall back to
Playwright on x.com which can extract posts before login walls appear.

Set NITTER_INSTANCES (comma-separated URLs) in .env to override the default list.
"""
import html as _html_mod
import http.cookiejar
import json
import os
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

_NITTER_DEFAULTS = [
    "https://nitter.tux.pizza",
    "https://nitter.cz",
    "https://nitter.rawbit.ninja",
    "https://n.opnxng.com",
    "https://nitter.privacyredirect.com",
    "https://xcancel.com",
]


def _get_nitter_instances() -> list[str]:
    """Return nitter instance list from NITTER_INSTANCES env var, or fall back to defaults."""
    env = os.getenv("NITTER_INSTANCES", "").strip()
    if env:
        return [u.strip() for u in env.split(",") if u.strip()]
    return _NITTER_DEFAULTS


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
        for base in _get_nitter_instances():
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

def _parse_count(raw: str) -> int:
    """Parse engagement counts like '10K', '1.2M', '45', '' → int."""
    raw = raw.strip().replace(",", "")
    if not raw:
        return 0
    try:
        if raw.endswith("K"):
            return int(float(raw[:-1]) * 1_000)
        if raw.endswith("M"):
            return int(float(raw[:-1]) * 1_000_000)
        return int(raw)
    except ValueError:
        return 0


def _stat_pw(article, testid: str) -> int:
    """Extract engagement count from a tweet article by data-testid."""
    loc = article.locator(f'[data-testid="{testid}"]')
    if not loc.count():
        return 0
    try:
        return _parse_count(loc.first.inner_text(timeout=1500))
    except Exception:
        return 0


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
        page.route("**/*.{png,jpg,jpeg,gif,mp4,webm,svg,woff,woff2}", lambda r: r.abort())

        try:
            page.goto(f"https://x.com/{handle}", timeout=30000, wait_until="domcontentloaded")
            try:
                page.wait_for_selector('article[data-testid="tweet"]', timeout=10000)
            except Exception:
                page.keyboard.press("Escape")
                page.wait_for_timeout(2000)

            articles = page.locator('article[data-testid="tweet"]').all()
            for article in articles[:limit]:
                try:
                    text_loc = article.locator('[data-testid="tweetText"]').first
                    if not text_loc.count():
                        continue
                    text = text_loc.inner_text(timeout=2000)
                    if not text:
                        continue

                    time_loc = article.locator("time").first
                    date = time_loc.get_attribute("datetime", timeout=1500) if time_loc.count() else ""

                    posts.append({
                        "text": text,
                        "date": date or "",
                        "likes": _stat_pw(article, "like"),
                        "retweets": _stat_pw(article, "retweet"),
                        "replies": _stat_pw(article, "reply"),
                    })
                except Exception:
                    pass
        finally:
            browser.close()

    return posts
