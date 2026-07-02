"""
Auto-apply (提案) to freelance cases on tasker.com.tw.

The site is a Nuxt SPA backed by a JSON API at api.tasker.com.tw. Clicking
我要提案 in the browser just calls that API and hydrates an in-memory store, so
driving the DOM is brittle (the propose form lives at /cases/propose and only
binds to a case via a store the click populates). Instead this tool talks to the
same API the site uses, which is deterministic and reliable:

  GET  /api/issue/{tk_no}/proposal        -> case title / content / budget /
                                             my existing proposal_content
  GET  /api/issue/{tk_no}/proposal/check  -> {status, data:{can_propose}}
  POST /api/issue/{tk_no}/proposal        -> submit (multipart form-data:
                                             initial_price_min, initial_price_max,
                                             content, quota_amount)

Auth is a per-session `Authorization: Bearer <token>` the SPA derives from the
logged-in cookies. The token isn't in a readable storage key, so we capture it
at runtime from any api.tasker.com.tw request the page makes after loading with
the persisted session (created once via `scripts/tasker_login.py`).

Flow per run:
  1. Load tasker.com.tw with the saved session; capture the Bearer token.
  2. Collect open case ids from /cases?selected_categories=<ids> (DOM).
  3. For each case: check eligibility, skip if already proposed / own / expired,
     generate a 提案說明 via `proposal_fn`, and POST the proposal — unless
     dry_run, which prepares everything but never submits (default).

`run_tasker_apply(...)` is the primary entry point (the flow calls it directly
with an LLM-backed proposal_fn). `TaskerApplyTool` is a thin BaseTool wrapper
using a static template, for catalog/agent parity.
"""
import os
import re
from typing import Callable

from crewai.tools import BaseTool
from pydantic import BaseModel

_BASE = "https://www.tasker.com.tw"
_API = "https://api.tasker.com.tw"
DEFAULT_STATE_PATH = "data/tasker_state.json"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# Case ids look like TK26062904IFZF37
_CASE_ID_RE = re.compile(r"/cases/(TK[0-9A-Z]+)", re.IGNORECASE)
_MIN_CHARGE_FLOOR = 1000  # site rule: 最低金額不可小於 1000

# proposal/check error statuses → human reason
_CHECK_ERRORS = {
    "1230075": "not eligible to propose (您尚未具備提案資格)",
    "4030075": "case expired (此案件已失效)",
    "4030213": "your own case (您無法對自己的案件提案)",
}
# postProposal error statuses → human reason
_SUBMIT_ERRORS = {
    "2700071": "proposal text format error (提案說明格式錯誤)",
    "2700247": "min price missing/invalid (初次報價最小值未填或格式錯誤)",
    "2700248": "max price missing/invalid (初次報價最大值未填或格式錯誤)",
    "1230075": "not eligible to propose (您尚未具備提案資格)",
}

_DEFAULT_TEMPLATE = (
    "您好，我對這個案件很有興趣。我具備完成此需求的相關經驗，"
    "能依您的規格與時程交付，並在過程中保持清楚溝通。"
    "上方為我的初步估價，實際費用可依細節討論調整。期待與您合作，謝謝！"
)


def _noop(_msg: str) -> None:
    pass


# ── session / auth ───────────────────────────────────────────────────────────

def _looks_logged_out(page) -> bool:
    """Reliable positive signals (登出 / 會員代碼 / avatar) beat the ever-present
    /auth/login link the site keeps in the header even when authenticated."""
    if "/auth/login" in page.url or "/auth/legacy" in page.url:
        return True
    try:
        for sel in (':text("登出")', ':text("會員代碼")', 'img[src*="avatar"]'):
            if page.locator(sel).count() > 0:
                return False
    except Exception:  # noqa: BLE001
        pass
    try:
        loc = page.locator('a[href*="/auth/login"], a:has-text("立即登入")')
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:  # noqa: BLE001
        return False


def _capture_session(page, category_ids: str, log: Callable) -> str | None:
    """Load the category listing with the saved session and capture the Bearer
    token from any api.tasker.com.tw request. Returns the token or None."""
    holder = {"bearer": None}

    def _on_request(req):
        if holder["bearer"]:
            return
        if "api.tasker.com.tw" in req.url:
            auth = req.headers.get("authorization")
            if auth and auth.lower().startswith("bearer "):
                holder["bearer"] = auth

    page.on("request", _on_request)
    url = f"{_BASE}/cases?selected_categories={category_ids}"
    log(f"Opening {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    # Poll: the SPA fires member/user API calls (carrying the token) after load.
    for _ in range(16):
        if holder["bearer"]:
            break
        page.wait_for_timeout(500)

    if _looks_logged_out(page) and not holder["bearer"]:
        return None
    if not holder["bearer"]:
        log("Logged in but no API token captured yet; retrying via a case page...")
        # Any authenticated page reliably fires a token-bearing request.
        page.goto(f"{_BASE}/users/tasker/proposal-management",
                  wait_until="domcontentloaded", timeout=30000)
        for _ in range(12):
            if holder["bearer"]:
                break
            page.wait_for_timeout(500)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
    return holder["bearer"]


def _headers(bearer: str) -> dict:
    return {
        "authorization": bearer,
        "accept": "application/json",
        "origin": _BASE,
        "referer": _BASE + "/",
        "user-agent": _UA,
    }


# ── case discovery (DOM) ─────────────────────────────────────────────────────

def _collect_case_ids(page, category_ids: str, max_cases: int, log: Callable) -> list[str]:
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
            m = _CASE_ID_RE.search(h or "")
            if not m:
                continue
            cid = m.group(1).upper()
            if cid not in seen_set:
                seen_set.add(cid)
                seen.append(cid)
        if len(seen) >= max_cases:
            break
        if len(seen) == prev:
            break
        prev = len(seen)
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(1000)
    log(f"Found {len(seen)} case link(s) in category {category_ids}")
    return seen[:max_cases]


# ── API calls ────────────────────────────────────────────────────────────────

def _get_json(ctx_request, bearer: str, path: str) -> dict | None:
    try:
        resp = ctx_request.get(f"{_API}{path}", headers=_headers(bearer), timeout=20000)
        return resp.json()
    except Exception:  # noqa: BLE001
        return None


def _case_info(ctx_request, bearer: str, cid: str) -> dict:
    """Title / description / budget / my existing proposal for a case."""
    d = _get_json(ctx_request, bearer, f"/api/issue/{cid}/proposal") or {}
    data = d.get("data") if isinstance(d.get("data"), dict) else d
    if not isinstance(data, dict):
        data = {}
    return {
        "title": data.get("title", "") or "",
        "content": data.get("content", "") or "",
        "budget_text": data.get("budget_text", "") or "",
        "proposal_content": data.get("proposal_content", "") or "",
    }


def _check(ctx_request, bearer: str, cid: str) -> tuple[bool, str]:
    """Can we propose to this case? Returns (ok, reason_if_not)."""
    d = _get_json(ctx_request, bearer, f"/api/issue/{cid}/proposal/check")
    if not isinstance(d, dict):
        return False, "eligibility check failed (no response)"
    status = str(d.get("status"))
    if status == "0":
        data = d.get("data") or {}
        if data.get("can_propose"):
            return True, ""
        return False, "cannot propose (can_propose=false)"
    return False, _CHECK_ERRORS.get(status, f"eligibility check failed (status {status})")


def _submit(ctx_request, bearer: str, cid: str, min_charge: int, max_charge: int,
            content: str) -> tuple[bool, str]:
    """POST the proposal as multipart form-data. Returns (ok, message)."""
    try:
        resp = ctx_request.post(
            f"{_API}/api/issue/{cid}/proposal",
            headers=_headers(bearer),
            multipart={
                "initial_price_min": str(min_charge),
                "initial_price_max": str(max_charge),
                "content": content,
                "quota_amount": "0",
            },
            timeout=30000,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    try:
        d = resp.json()
    except Exception:  # noqa: BLE001
        return (resp.status == 200), f"HTTP {resp.status}"
    status = str(d.get("status"))
    if resp.status == 200 and status == "0":
        return True, "ok"
    return False, _SUBMIT_ERRORS.get(status, f"submit failed (status {status})")


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
    username = os.getenv("TASKER_USERNAME", "")  # noqa: F841 (kept for parity/logs)
    max_cases = max(1, min(int(max_cases), 50))

    base = {"category_ids": category_ids, "dry_run": dry_run,
            "applied": [], "skipped": []}

    if not (state_path and os.path.exists(state_path)):
        return {**base, "error": (
            f"No saved tasker.com.tw session at '{state_path}'. Run "
            "`uv run python scripts/tasker_login.py` once to log in and save it."
        )}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            storage_state=state_path,
            user_agent=_UA,
            locale="zh-TW",
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.new_page()
        try:
            bearer = _capture_session(page, category_ids, log)
            if not bearer:
                return {**base, "error": (
                    "Not logged in / could not obtain an API token. The saved "
                    "session may have expired — re-run "
                    "`uv run python scripts/tasker_login.py`."
                )}
            log("✓ Authenticated with tasker.com.tw API")

            case_ids = _collect_case_ids(page, category_ids, max_cases, log)
            if not case_ids:
                return {**base, "cases_found": 0,
                        "summary": f"No open cases found for category {category_ids}."}

            if min_charge < _MIN_CHARGE_FLOOR:
                log(f"⚠ min_charge {min_charge} is below the site minimum "
                    f"{_MIN_CHARGE_FLOOR}; submissions may be rejected.")

            applied: list[dict] = []
            skipped: list[dict] = []
            for i, cid in enumerate(case_ids, 1):
                url = f"{_BASE}/cases/{cid}"
                log(f"[{i}/{len(case_ids)}] {cid}")
                entry = {"case_id": cid, "url": url}
                try:
                    info = _case_info(ctx.request, bearer, cid)
                    entry["title"] = (info.get("title") or cid)[:200]

                    if info.get("proposal_content"):
                        entry.update(status="skipped", reason="already proposed")
                        log(f"↷ {cid}: already proposed — skipping")
                        skipped.append(entry)
                        continue

                    ok, reason = _check(ctx.request, bearer, cid)
                    if not ok:
                        entry.update(status="skipped", reason=reason)
                        log(f"↷ {cid}: {reason} — skipping")
                        skipped.append(entry)
                        continue

                    proposal = (proposal_fn(info.get("title", ""),
                                            info.get("content", "")) or "").strip() \
                        or _DEFAULT_TEMPLATE
                    entry.update(min_charge=min_charge, max_charge=max_charge,
                                 proposal=proposal[:500])

                    if dry_run:
                        entry.update(status="prepared", submitted=False, reason="dry_run")
                        log(f"✓ {cid}: proposal prepared (dry-run, NOT submitted)")
                        applied.append(entry)
                        continue

                    sok, smsg = _submit(ctx.request, bearer, cid,
                                        min_charge, max_charge, proposal)
                    if sok:
                        entry.update(status="submitted", submitted=True)
                        log(f"✓ {cid}: 提案 submitted")
                        applied.append(entry)
                    else:
                        entry.update(status="failed", submitted=False, reason=smsg)
                        log(f"✗ {cid}: submit failed — {smsg}")
                        skipped.append(entry)
                except Exception as exc:  # noqa: BLE001 — one bad case shouldn't stop the run
                    entry.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
                    log(f"✗ {cid}: {type(exc).__name__}: {exc}")
                    skipped.append(entry)

            submitted_n = sum(1 for e in applied if e.get("submitted"))
            verb = "prepared (dry-run)" if dry_run else "submitted"
            summary = (
                f"Category {category_ids}: {len(case_ids)} case(s) scanned, "
                f"{len(applied)} {verb}, {len(skipped)} skipped."
            )
            return {
                **base,
                "cases_found": len(case_ids),
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
        "Log in to tasker.com.tw and auto-apply (提案) to open cases in a category "
        "via its JSON API. Args: category_ids (e.g. '110' or '110,101001'), "
        "min_charge, max_charge, proposal_template, max_cases, dry_run. Checks "
        "eligibility, skips already-applied/own/expired cases, and submits the "
        "proposal only when dry_run is false."
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
