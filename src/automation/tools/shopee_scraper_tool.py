"""
Scrape sellers behind the top products for a Shopee (shopee.tw) search keyword.

Shopee requires a logged-in session and is heavily bot-protected, so this tool
reuses a PERSISTED browser session instead of logging in each run:

  1. Run the one-time helper once to log in manually (handles captcha / OTP):
         uv run python scripts/shopee_login.py
     It saves the storage state (cookies + localStorage) to the path in
     SHOPEE_STORAGE_STATE (default: data/shopee_state.json).
  2. This tool loads that state into a headless Chromium context, so every
     request is authenticated.

Strategy: prefer Shopee's internal JSON API (search_items + get_shop_detail)
issued through the authenticated browser context — it carries the session
cookies and is far more reliable than DOM scraping. Falls back to DOM scraping
of the search/product pages if the API is blocked.
"""
import os
import re
import urllib.parse
from datetime import UTC, datetime

from crewai.tools import BaseTool
from pydantic import BaseModel

DEFAULT_STATE_PATH = "data/shopee_state.json"
_BASE = "https://shopee.tw"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# Matches Shopee product URLs ending in "-i.{shopid}.{itemid}".
_IID_RE = re.compile(r"-i\.(\d+)\.(\d+)")


class ShopeeScrapeInput(BaseModel):
    keyword: str
    limit: int = 5


class ShopeeSellerScraperTool(BaseTool):
    name: str = "shopee_seller_scraper"
    description: str = (
        "Search shopee.tw for a keyword, open the top N products, and collect "
        "the seller (shop) behind each one: shop name, shop URL, location, "
        "join date, rating, rating count, follower count, item count, and "
        "response rate. Args: keyword (str), limit (int, number of products)."
    )
    args_schema: type[BaseModel] = ShopeeScrapeInput

    def _run(self, keyword: str, limit: int = 5) -> dict:
        limit = max(1, min(int(limit), 20))
        state_path = os.getenv("SHOPEE_STORAGE_STATE", DEFAULT_STATE_PATH)
        username = os.getenv("SHOPEE_USERNAME", "")
        password = os.getenv("SHOPEE_PASSWORD", "")

        # No saved session yet — try an automated login with the .env credentials.
        # Shopee usually blocks headless logins with captcha/OTP, so this is a
        # best-effort fallback; the reliable path is `scripts/shopee_login.py`.
        if not os.path.exists(state_path):
            if username and password:
                try:
                    _login_with_credentials(state_path, username, password)
                except Exception as exc:  # noqa: BLE001
                    return {
                        "keyword": keyword, "sellers": [],
                        "error": (
                            f"Auto-login failed ({type(exc).__name__}: {exc}). Shopee likely "
                            "required a captcha/OTP. Run `uv run python scripts/shopee_login.py` "
                            "once to log in manually and save the session."
                        ),
                    }
            if not os.path.exists(state_path):
                return {
                    "keyword": keyword, "sellers": [],
                    "error": (
                        f"No Shopee session at '{state_path}' and no usable SHOPEE_USERNAME/"
                        "SHOPEE_PASSWORD in .env. Log in once with "
                        "`uv run python scripts/shopee_login.py`."
                    ),
                }

        try:
            return _scrape(keyword, limit, state_path)
        except Exception as exc:  # noqa: BLE001 — surface a clean error to the agent
            return {
                "keyword": keyword,
                "sellers": [],
                "error": f"{type(exc).__name__}: {exc}",
            }


# ── credential auto-login (best-effort fallback) ─────────────────────────────────

def _login_with_credentials(state_path: str, username: str, password: str) -> None:
    """Attempt a headless login with .env credentials and persist the session.

    Best-effort only: Shopee commonly interrupts headless logins with a captcha
    or SMS/email OTP, in which case no session is saved and the caller falls back
    to the manual `scripts/shopee_login.py` helper. Raises on hard failures.
    """
    from playwright.sync_api import sync_playwright

    os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(user_agent=_UA, locale="zh-TW",
                                  viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        try:
            page.goto(f"{_BASE}/buyer/login", wait_until="domcontentloaded", timeout=30_000)
            page.locator('input[name="loginKey"]').first.fill(username, timeout=10_000)
            page.locator('input[name="password"]').first.fill(password, timeout=10_000)
            page.locator('button:has-text("登入"), button:has-text("Log In")').first.click(timeout=10_000)
            page.wait_for_timeout(5000)

            # Only persist if we actually left the login page (no captcha/OTP wall).
            if "/buyer/login" not in page.url:
                ctx.storage_state(path=state_path)
        finally:
            browser.close()


# ── orchestration ───────────────────────────────────────────────────────────────

def _scrape(keyword: str, limit: int, state_path: str) -> dict:
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            storage_state=state_path,
            user_agent=_UA,
            viewport={"width": 1366, "height": 900},
            locale="zh-TW",
        )
        page = ctx.new_page()
        try:
            # Warm up the session so cookies / anti-bot tokens are in place.
            page.goto(_BASE, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(1500)

            products = _search_api(page, keyword, limit, errors) \
                or _search_dom(page, keyword, limit, errors)

            if not products:
                return {
                    "keyword": keyword,
                    "sellers": [],
                    "error": "No products found — " + (" | ".join(errors[:4]) or "empty result"),
                }

            # One seller per unique shop, preserving search order, up to limit.
            sellers: list[dict] = []
            seen: set[int] = set()
            for prod in products:
                shopid = prod["shopid"]
                if shopid in seen:
                    continue
                seen.add(shopid)
                seller = _shop_detail_api(page, shopid, errors)
                if seller is None:
                    seller = {"shop_name": "", "shop_url": f"{_BASE}/shop/{shopid}"}
                seller["product_title"] = prod.get("name", "")
                seller["product_url"] = prod.get("url", "")
                sellers.append(seller)
                if len(sellers) >= limit:
                    break

            result = {
                "keyword": keyword,
                "source": "shopee.tw",
                "seller_count": len(sellers),
                "sellers": sellers,
            }
            if not sellers and errors:
                result["error"] = " | ".join(errors[:4])
            return result
        finally:
            browser.close()


# ── Shopee internal API (preferred) ───────────────────────────────────────────────

def _api_get(page, path: str, errors: list[str]) -> dict | None:
    """GET a Shopee API path through the authenticated context; return parsed JSON."""
    try:
        resp = page.request.get(
            f"{_BASE}{path}",
            headers={
                "Referer": _BASE + "/",
                "X-Requested-With": "XMLHttpRequest",
                "X-API-SOURCE": "pc",
                "Accept": "application/json",
            },
            timeout=20_000,
        )
        if resp.status != 200:
            errors.append(f"api {path.split('?')[0]}: HTTP {resp.status}")
            return None
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"api {path.split('?')[0]}: {type(exc).__name__}")
        return None


def _search_api(page, keyword: str, limit: int, errors: list[str]) -> list[dict]:
    kw = urllib.parse.quote(keyword)
    path = (
        f"/api/v4/search/search_items?by=relevancy&keyword={kw}"
        f"&limit={limit}&newest=0&order=desc&page_type=search"
        f"&scenario=PAGE_GLOBAL_SEARCH&version=2"
    )
    data = _api_get(page, path, errors)
    if not data:
        return []
    items = data.get("items") or []
    products: list[dict] = []
    for entry in items:
        basic = entry.get("item_basic") or entry.get("basic") or entry
        shopid, itemid = basic.get("shopid"), basic.get("itemid")
        if not shopid or not itemid:
            continue
        products.append({
            "shopid": int(shopid),
            "itemid": int(itemid),
            "name": basic.get("name", ""),
            "url": f"{_BASE}/product/{shopid}/{itemid}",
        })
    if not products:
        errors.append("api search: no items in payload")
    return products


def _shop_detail_api(page, shopid: int, errors: list[str]) -> dict | None:
    data = _api_get(page, f"/api/v4/shop/get_shop_detail?shopid={shopid}", errors)
    if not data:
        return None
    d = data.get("data") or {}
    if not d:
        return None
    username = (d.get("account") or {}).get("username", "")
    return {
        "shop_name": d.get("name", "") or username,
        "shop_url": f"{_BASE}/{username}" if username else f"{_BASE}/shop/{shopid}",
        "location": d.get("shop_location", ""),
        "joined": _epoch_to_date(d.get("ctime")),
        "rating_star": round(float(d.get("rating_star") or 0), 2),
        "rating_count": _rating_total(d),
        "follower_count": d.get("follower_count", 0),
        "item_count": d.get("item_count", 0),
        "response_rate": d.get("response_rate", 0),
    }


def _rating_total(d: dict) -> int:
    return sum(int(d.get(k) or 0) for k in ("rating_bad", "rating_normal", "rating_good"))


def _epoch_to_date(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=UTC).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


# ── DOM fallback ────────────────────────────────────────────────────────────────

def _search_dom(page, keyword: str, limit: int, errors: list[str]) -> list[dict]:
    """Scrape product links off the rendered search page when the API is blocked."""
    kw = urllib.parse.quote(keyword)
    try:
        page.goto(f"{_BASE}/search?keyword={kw}", wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector('a[href*="-i."]', timeout=15_000)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"dom search: {type(exc).__name__}")
        return []

    products: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for a in page.locator('a[href*="-i."]').all():
        href = a.get_attribute("href") or ""
        m = _IID_RE.search(href)
        if not m:
            continue
        shopid, itemid = int(m.group(1)), int(m.group(2))
        if (shopid, itemid) in seen:
            continue
        seen.add((shopid, itemid))
        name = (a.get_attribute("aria-label") or a.inner_text() or "").strip()[:200]
        products.append({
            "shopid": shopid,
            "itemid": itemid,
            "name": name,
            "url": urllib.parse.urljoin(_BASE, href),
        })
        if len(products) >= limit:
            break
    if not products:
        errors.append("dom search: no product links matched")
    return products
