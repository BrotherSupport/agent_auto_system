"""
Discover SMBs / businesses from Google Maps for a search query + region.

This is stage 1 of the lead-collection funnel (see doc/email_collect):
    DISCOVER  →  extract email  →  verify  →  dedupe

Google Maps has no free structured export, so we drive a headless Chromium
session with Playwright: run the search, scroll the results feed to load N
listings, then open each place panel to read its website, phone, address, and
category. The business's own **website** is what the next stage scrapes for an
email — Maps itself rarely exposes one.

Selectors track Google Maps' current consumer DOM (class names like `hfpxzc` /
`DUwDvf` are Google's own and do change over time); every field read is guarded
so a markup shift degrades a single field rather than failing the whole run.
Partial results + a `warnings` list are returned instead of raising, matching
the other scraper tools in this package.
"""
import re
import urllib.parse

from crewai.tools import BaseTool
from pydantic import BaseModel

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_BASE = "https://www.google.com/maps/search/"
_PHONE_PREFIX = "phone:tel:"


class MapsSearchInput(BaseModel):
    query: str
    region: str = ""
    limit: int = 15


class MapsSearchTool(BaseTool):
    name: str = "maps_search"
    description: str = (
        "Search Google Maps for businesses matching a query in a region and "
        "return each listing's name, website, phone, address, and category. "
        "Args: query (str, e.g. 'AI agency'), region (str, e.g. 'Taipei' or "
        "'Berlin'), limit (int, number of listings). The website field feeds "
        "the email-extraction stage."
    )
    args_schema: type[BaseModel] = MapsSearchInput

    def _run(self, query: str, region: str = "", limit: int = 15) -> dict:
        return search_maps(query, region, limit)


def search_maps(query: str, region: str = "", limit: int = 15, log=None) -> dict:
    """Discover up to `limit` businesses for `query` in `region`.

    Returns {"query", "region", "businesses": [...], "warnings": [...]}.
    Each business: {name, website, phone, address, category, maps_url}.
    """
    limit = max(1, min(int(limit), 500))
    _log = log or (lambda _m: None)
    term = f"{query} {region}".strip()
    warnings: list[str] = []

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return {"query": query, "region": region, "businesses": [],
                "warnings": [f"playwright unavailable: {exc}"]}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--lang=en-US"],
        )
        ctx = browser.new_context(
            user_agent=_UA, locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.new_page()
        try:
            url = f"{_BASE}{urllib.parse.quote(term)}?hl=en"
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            _dismiss_consent(page)

            place_urls = _collect_place_urls(page, limit, warnings, _log)
            if not place_urls:
                warnings.append("no listings found in results feed")

            businesses: list[dict] = []
            for i, purl in enumerate(place_urls[:limit], 1):
                _log(f"Opening listing {i}/{min(len(place_urls), limit)}...")
                biz = _read_place(page, purl, warnings)
                if biz and biz.get("name"):
                    businesses.append(biz)

            return {"query": query, "region": region,
                    "businesses": businesses, "warnings": warnings[:8]}
        finally:
            browser.close()


def _dismiss_consent(page) -> None:
    """Best-effort click through Google's EU consent wall if it appears."""
    if "consent." not in page.url and "consent" not in (page.title() or "").lower():
        return
    for label in ("Reject all", "Accept all", "I agree", "拒絕全部", "全部接受"):
        try:
            btn = page.locator(f'button:has-text("{label}")').first
            if btn.count():
                btn.click(timeout=4_000)
                page.wait_for_timeout(1_500)
                return
        except Exception:  # noqa: BLE001 — try the next label / proceed anyway
            continue


def _collect_place_urls(page, limit: int, warnings: list[str], log) -> list[str]:
    """Scroll the results feed until it holds >= limit place links (or stalls)."""
    try:
        page.wait_for_selector('a[href*="/maps/place/"]', timeout=15_000)
    except Exception:  # noqa: BLE001
        warnings.append("results feed did not render")
        return []

    seen: list[str] = []
    seen_set: set[str] = set()
    stale = 0
    for _ in range(20):
        prev = len(seen_set)  # count before this pass, to detect a stalled feed
        hrefs = page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href*="/maps/place/"]'))
                       .map(a => a.href)"""
        )
        for h in hrefs:
            if h not in seen_set:
                seen_set.add(h)
                seen.append(h)
        if len(seen) >= limit:
            break
        # Stop early once the feed stops yielding new listings for a few passes.
        if len(seen_set) == prev:
            stale += 1
            if stale >= 3:
                break
        else:
            stale = 0
        # Scroll the feed container (not the window) to trigger lazy-loading.
        try:
            page.evaluate(
                """() => { const f = document.querySelector('div[role="feed"]');
                           if (f) f.scrollBy(0, f.scrollHeight); }"""
            )
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1_600)
    log(f"Discovered {len(seen)} listing link(s)")
    return seen


def _read_place(page, purl: str, warnings: list[str]) -> dict | None:
    try:
        page.goto(purl, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector("h1", timeout=10_000)
        page.wait_for_timeout(600)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"place load failed: {type(exc).__name__}")
        return None

    return {
        "name":     _text(page, "h1.DUwDvf") or _text(page, "h1"),
        "website":  _attr(page, 'a[data-item-id="authority"]', "href"),
        "phone":    _phone(page),
        "address":  _aria_after(page, 'button[data-item-id="address"]'),
        "category": _text(page, 'button[jsaction*="category"]'),
        "maps_url": purl,
    }


def _text(page, selector: str) -> str:
    try:
        loc = page.locator(selector).first
        if loc.count():
            return (loc.inner_text(timeout=2_000) or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _attr(page, selector: str, attr: str) -> str:
    try:
        loc = page.locator(selector).first
        if loc.count():
            return (loc.get_attribute(attr, timeout=2_000) or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _aria_after(page, selector: str) -> str:
    """Read a button's aria-label and drop the leading 'Label: ' prefix."""
    raw = _attr(page, selector, "aria-label")
    return re.sub(r"^[^:]{1,20}:\s*", "", raw).strip() if raw else ""


def _phone(page) -> str:
    item = _attr(page, f'button[data-item-id^="{_PHONE_PREFIX}"]', "data-item-id")
    if item and _PHONE_PREFIX in item:
        return item.split(_PHONE_PREFIX, 1)[1].strip()
    return _aria_after(page, 'button[data-item-id^="phone"]')
