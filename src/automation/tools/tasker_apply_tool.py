"""
Auto-apply (提案) to freelance cases on tasker.com.tw.

Flow per run:
  1. Log in. tasker.com.tw is a JS-rendered SPA whose login is phone-based and
     often guarded by captcha/OTP, so — like the Shopee scraper — the reliable
     path is a PERSISTED session created once with a real browser:
         uv run python scripts/tasker_login.py
     which writes cookies/localStorage to TASKER_STORAGE_STATE
     (default: data/tasker_state.json). This tool loads that state headlessly.
     If no session exists it falls back to a best-effort headless login with the
     TASKER_USERNAME / TASKER_PASSWORD credentials in .env.
  2. Open the category listing: /cases?selected_categories=<ids>
  3. For each open case (skipping ones already proposed on), open the case,
     click 我要提案, fill the 初次估價 min/max charge, fill 提案說明 (text supplied
     by `proposal_fn`, typically LLM-generated), and — unless dry_run — click
     送出提案.

Because the logged-in DOM can't be inspected offline, every interaction uses
resilient, text-first locators with several fallbacks and logs what it does.
`dry_run` defaults to True so the first run can be observed safely before any
real proposal is submitted.

The primary entry point is `run_tasker_apply(...)`, a plain function the flow
calls directly (it accepts a `proposal_fn` callback the crew/LLM path can't pass
through a CrewAI tool). `TaskerApplyTool` is a thin BaseTool wrapper that uses a
static template proposal, provided for catalog/agent parity.
"""
import os
import re
from typing import Callable

from crewai.tools import BaseTool
from pydantic import BaseModel

_BASE = "https://www.tasker.com.tw"
DEFAULT_STATE_PATH = "data/tasker_state.json"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# Case detail URLs look like /cases/TK26062904IFZF37
_CASE_HREF_RE = re.compile(r"/cases/(TK[0-9A-Z]+)", re.IGNORECASE)

_DEFAULT_TEMPLATE = (
    "您好，我對這個案件很有興趣。我具備完成此需求的相關經驗，"
    "能依您的規格與時程交付，並在過程中保持清楚溝通。"
    "上方為我的初步估價，實際費用可依細節討論調整。期待與您合作，謝謝！"
)


def _noop(_msg: str) -> None:
    pass


# ── session / login ────────────────────────────────────────────────────────────

def _looks_logged_out(page) -> bool:
    """Heuristic: are we on / redirected to a login wall?"""
    if "/auth/login" in page.url or "/auth/legacy" in page.url:
        return True
    try:
        # A visible top-level 登入 / 立即登入 entry point means no active session.
        loc = page.locator('a[href*="/auth/login"], a:has-text("立即登入")')
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:  # noqa: BLE001
        return False


def _first_fillable(page, selectors: list[str], value: str, log: Callable, what: str) -> bool:
    """Fill the first visible input matching any of `selectors`. Returns success."""
    for sel in selectors:
        try:
            loc = page.locator(sel)
            n = loc.count()
            for i in range(n):
                item = loc.nth(i)
                if item.is_visible():
                    item.fill(value, timeout=8000)
                    return True
        except Exception:  # noqa: BLE001
            continue
    log(f"⚠ could not find a field for {what}")
    return False


def _do_login(page, username: str, password: str, log: Callable) -> None:
    """Best-effort headless login. May be blocked by captcha/OTP."""
    # Email-style accounts use the non-phone (legacy) form; phone numbers use the
    # default form. /auth/legacy exposes plain account + password inputs.
    login_url = f"{_BASE}/auth/legacy" if "@" in username else f"{_BASE}/auth/login"
    log(f"Attempting login at {login_url} ...")
    page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1500)

    _first_fillable(
        page,
        [
            'input[type="email"]',
            'input[name*="account" i]', 'input[name*="email" i]',
            'input[name*="phone" i]', 'input[name*="mobile" i]', 'input[name*="user" i]',
            'input[placeholder*="帳號"]', 'input[placeholder*="信箱"]',
            'input[placeholder*="手機"]', 'input[placeholder*="電話"]', 'input[placeholder*="Email" i]',
        ],
        username, log, "username/account",
    )
    _first_fillable(
        page,
        [
            'input[type="password"]',
            'input[name*="password" i]', 'input[placeholder*="密碼"]',
        ],
        password, log, "password",
    )

    # Submit: try a labelled button, else press Enter in the password field.
    clicked = False
    for sel in ['button:has-text("登入")', 'button[type="submit"]', 'button:has-text("Login")']:
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible():
                btn.click(timeout=8000)
                clicked = True
                break
        except Exception:  # noqa: BLE001
            continue
    if not clicked:
        try:
            page.locator('input[type="password"]').first.press("Enter")
        except Exception:  # noqa: BLE001
            pass
    page.wait_for_timeout(4000)


def _ensure_session(page, ctx, state_path: str, username: str, password: str, log: Callable) -> bool:
    """Make sure we land on the cases area logged in. Returns True if logged in."""
    cases_url = f"{_BASE}/cases"
    page.goto(cases_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1500)

    if not _looks_logged_out(page):
        return True

    if not (username and password):
        log("No active session and no TASKER_USERNAME/TASKER_PASSWORD in .env.")
        return False

    _do_login(page, username, password, log)
    # Re-check by returning to the cases area.
    page.goto(cases_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1500)
    if _looks_logged_out(page):
        log("Login appears to have failed (captcha/OTP?). "
            "Run `uv run python scripts/tasker_login.py` once to save a session.")
        return False

    # Persist the freshly-authenticated session for next time.
    try:
        os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
        ctx.storage_state(path=state_path)
        log(f"✓ Saved login session to {state_path}")
    except Exception as exc:  # noqa: BLE001
        log(f"· Could not persist session: {exc}")
    return True


# ── case discovery ───────────────────────────────────────────────────────────

def _collect_case_urls(page, category_ids: str, max_cases: int, log: Callable) -> list[str]:
    url = f"{_BASE}/cases?selected_categories={category_ids}"
    log(f"Opening {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2500)

    # Scroll to trigger lazy-loaded cards until enough links or no growth.
    seen: list[str] = []
    seen_set: set[str] = set()
    prev = -1
    for _ in range(12):
        try:
            hrefs = page.evaluate(
                "() => Array.from(document.querySelectorAll('a[href*=\"/cases/\"]'))"
                ".map(a => a.getAttribute('href') || '')"
            )
        except Exception:  # noqa: BLE001
            hrefs = []
        for h in hrefs:
            m = _CASE_HREF_RE.search(h or "")
            if not m:
                continue
            case_id = m.group(1).upper()
            full = f"{_BASE}/cases/{case_id}"
            if full not in seen_set:
                seen_set.add(full)
                seen.append(full)
        if len(seen) >= max_cases:
            break
        if len(seen) == prev:
            break
        prev = len(seen)
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(1000)

    log(f"Found {len(seen)} case link(s) in category {category_ids}")
    return seen[:max_cases]


def _text_or(page, selector: str, default: str = "") -> str:
    try:
        loc = page.locator(selector).first
        if loc.count():
            return (loc.inner_text(timeout=4000) or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return default


# ── proposal submission ──────────────────────────────────────────────────────

def _find_apply_button(page):
    """Return a visible 我要提案 button/link locator, or None."""
    for sel in ['button:has-text("我要提案")', 'a:has-text("我要提案")', ':text("我要提案")']:
        try:
            loc = page.locator(sel)
            for i in range(loc.count()):
                item = loc.nth(i)
                if item.is_visible():
                    return item
        except Exception:  # noqa: BLE001
            continue
    return None


def _already_applied(page) -> bool:
    """Heuristic: the case shows a 已提案 / disabled-proposal state."""
    for sel in [':text("已提案")', ':text("修改提案")', ':text("您已提案")']:
        try:
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible():
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _fill_estimate(page, min_charge: int, max_charge: int, log: Callable) -> bool:
    """Fill the 初次估價 lowest/highest inputs. Best-effort with fallbacks."""
    lo = _first_fillable(
        page,
        [
            'input[placeholder*="最低"]', 'input[placeholder*="下限"]',
            'input[name*="min" i]', 'input[placeholder*="min" i]',
        ],
        str(min_charge), log, "min charge",
    )
    hi = _first_fillable(
        page,
        [
            'input[placeholder*="最高"]', 'input[placeholder*="上限"]',
            'input[name*="max" i]', 'input[placeholder*="max" i]',
        ],
        str(max_charge), log, "max charge",
    )
    if lo and hi:
        return True

    # Fallback: assume the first two visible number inputs are (min, max).
    try:
        nums = page.locator('input[type="number"]')
        visible = [nums.nth(i) for i in range(nums.count()) if nums.nth(i).is_visible()]
        if len(visible) >= 2:
            visible[0].fill(str(min_charge), timeout=8000)
            visible[1].fill(str(max_charge), timeout=8000)
            log("· filled estimate via number-input fallback")
            return True
    except Exception:  # noqa: BLE001
        pass
    return lo or hi


def _fill_proposal_text(page, text: str, log: Callable) -> bool:
    try:
        ta = page.locator("textarea")
        for i in range(ta.count()):
            item = ta.nth(i)
            if item.is_visible():
                item.fill(text, timeout=8000)
                return True
    except Exception:  # noqa: BLE001
        pass
    log("⚠ could not find the 提案說明 textarea")
    return False


def _click_submit(page, log: Callable) -> bool:
    for sel in ['button:has-text("送出提案")', 'button:has-text("送出")', 'a:has-text("送出提案")']:
        try:
            loc = page.locator(sel)
            for i in range(loc.count()):
                item = loc.nth(i)
                if item.is_visible():
                    item.click(timeout=8000)
                    page.wait_for_timeout(2500)
                    return True
        except Exception:  # noqa: BLE001
            continue
    log("⚠ could not find the 送出提案 button")
    return False


def _apply_to_case(page, case_url: str, min_charge: int, max_charge: int,
                   proposal_fn: Callable[[str, str], str], dry_run: bool,
                   log: Callable) -> dict:
    case_id = case_url.rstrip("/").split("/")[-1]
    page.goto(case_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)

    title = _text_or(page, "h1") or _text_or(page, "h2") or case_id
    entry = {"case_id": case_id, "url": case_url, "title": title[:200]}

    if _already_applied(page):
        entry.update(status="skipped", reason="already applied")
        log(f"↷ {case_id}: already applied — skipping")
        return entry

    apply_btn = _find_apply_button(page)
    if apply_btn is None:
        entry.update(status="skipped", reason="我要提案 button not found (closed/expired?)")
        log(f"↷ {case_id}: 我要提案 not available — skipping")
        return entry

    # Grab a chunk of the case description for the proposal writer before opening
    # the (often modal) proposal form, which can overlay the description.
    description = _text_or(page, "main") or _text_or(page, "body")
    description = description[:2000]

    try:
        apply_btn.click(timeout=8000)
    except Exception:  # noqa: BLE001
        apply_btn.click(timeout=8000, force=True)
    page.wait_for_timeout(2000)

    proposal = (proposal_fn(title, description) or "").strip() or _DEFAULT_TEMPLATE
    filled_estimate = _fill_estimate(page, min_charge, max_charge, log)
    filled_text = _fill_proposal_text(page, proposal, log)
    entry.update(min_charge=min_charge, max_charge=max_charge,
                 proposal=proposal[:500])

    if not (filled_estimate and filled_text):
        entry.update(status="skipped", reason="could not fill proposal form fields")
        log(f"↷ {case_id}: form fields incomplete — not submitting")
        return entry

    if dry_run:
        entry.update(status="prepared", submitted=False, reason="dry_run")
        log(f"✓ {case_id}: proposal prepared (dry-run, NOT submitted)")
        return entry

    if _click_submit(page, log):
        entry.update(status="submitted", submitted=True)
        log(f"✓ {case_id}: 送出提案 clicked")
    else:
        entry.update(status="failed", submitted=False, reason="submit button not found")
    return entry


# ── orchestration ────────────────────────────────────────────────────────────

def run_tasker_apply(
    *,
    category_ids: str,
    min_charge: int,
    max_charge: int,
    max_cases: int = 5,
    dry_run: bool = True,
    proposal_fn: Callable[[str, str], str] | None = None,
    log: Callable[[str], None] | None = None,
    state_path: str | None = None,
) -> dict:
    """Log in and apply to open cases in the given category. See module docstring."""
    from playwright.sync_api import sync_playwright

    log = log or _noop
    proposal_fn = proposal_fn or (lambda _t, _d: _DEFAULT_TEMPLATE)
    state_path = state_path or os.getenv("TASKER_STORAGE_STATE", DEFAULT_STATE_PATH)
    username = os.getenv("TASKER_USERNAME", "")
    password = os.getenv("TASKER_PASSWORD", "")
    max_cases = max(1, min(int(max_cases), 50))

    base = {"category_ids": category_ids, "dry_run": dry_run,
            "applied": [], "skipped": []}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx_kwargs = dict(user_agent=_UA, locale="zh-TW",
                          viewport={"width": 1366, "height": 900})
        if state_path and os.path.exists(state_path):
            ctx_kwargs["storage_state"] = state_path
            log(f"Loaded saved session from {state_path}")
        ctx = browser.new_context(**ctx_kwargs)
        page = ctx.new_page()
        # Skip heavy media to speed navigation.
        try:
            page.route(
                "**/*.{png,jpg,jpeg,gif,mp4,webm,svg,woff,woff2}",
                lambda r: r.abort(),
            )
        except Exception:  # noqa: BLE001
            pass

        try:
            if not _ensure_session(page, ctx, state_path, username, password, log):
                return {**base, "error": (
                    "Not logged in to tasker.com.tw. Run "
                    "`uv run python scripts/tasker_login.py` once to save a session, "
                    "or set TASKER_USERNAME/TASKER_PASSWORD in .env."
                )}

            case_urls = _collect_case_urls(page, category_ids, max_cases, log)
            if not case_urls:
                return {**base, "cases_found": 0,
                        "summary": f"No open cases found for category {category_ids}."}

            applied: list[dict] = []
            skipped: list[dict] = []
            for i, case_url in enumerate(case_urls, 1):
                log(f"[{i}/{len(case_urls)}] Processing {case_url}")
                try:
                    entry = _apply_to_case(page, case_url, min_charge, max_charge,
                                           proposal_fn, dry_run, log)
                except Exception as exc:  # noqa: BLE001 — one bad case shouldn't stop the run
                    entry = {"case_id": case_url.rstrip("/").split("/")[-1],
                             "url": case_url, "status": "failed",
                             "reason": f"{type(exc).__name__}: {exc}"}
                    log(f"✗ {case_url}: {type(exc).__name__}: {exc}")
                if entry.get("status") in ("submitted", "prepared"):
                    applied.append(entry)
                else:
                    skipped.append(entry)

            submitted_n = sum(1 for e in applied if e.get("submitted"))
            verb = "submitted" if not dry_run else "prepared (dry-run)"
            summary = (
                f"Category {category_ids}: {len(case_urls)} case(s) scanned, "
                f"{len(applied)} {verb}, {len(skipped)} skipped."
            )
            return {
                **base,
                "cases_found": len(case_urls),
                "applied": applied,
                "skipped": skipped,
                "applied_count": len(applied),
                "submitted_count": submitted_n,
                "skipped_count": len(skipped),
                "summary": summary,
            }
        finally:
            browser.close()


# ── BaseTool wrapper (static-template proposal; catalog/agent parity) ─────────

class TaskerApplyInput(BaseModel):
    category_ids: str
    min_charge: int
    max_charge: int
    proposal_template: str = _DEFAULT_TEMPLATE
    max_cases: int = 5
    dry_run: bool = True


class TaskerApplyTool(BaseTool):
    name: str = "tasker_apply"
    description: str = (
        "Log in to tasker.com.tw and auto-apply (提案) to open cases in a category. "
        "Args: category_ids (e.g. '110' or '110,101001'), min_charge, max_charge, "
        "proposal_template, max_cases, dry_run. Fills 初次估價 min/max and 提案說明, "
        "skips already-applied cases, and clicks 送出提案 only when dry_run is false."
    )
    args_schema: type[BaseModel] = TaskerApplyInput

    def _run(self, category_ids: str, min_charge: int, max_charge: int,
             proposal_template: str = _DEFAULT_TEMPLATE, max_cases: int = 5,
             dry_run: bool = True) -> dict:
        template = proposal_template or _DEFAULT_TEMPLATE

        def _proposal(title: str, _desc: str) -> str:
            try:
                return template.format(title=title)
            except Exception:  # noqa: BLE001 — template may lack {title}
                return template

        try:
            return run_tasker_apply(
                category_ids=category_ids, min_charge=min_charge, max_charge=max_charge,
                max_cases=max_cases, dry_run=dry_run, proposal_fn=_proposal,
            )
        except Exception as exc:  # noqa: BLE001
            return {"category_ids": category_ids, "applied": [], "skipped": [],
                    "error": f"{type(exc).__name__}: {exc}"}
