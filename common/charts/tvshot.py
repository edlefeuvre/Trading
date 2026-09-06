r"""common.charts.tvshot — a picture of Ed's own TradingView chart, taken by the server.

The 32-bar close wants the permanent chart image in the trade file. This module drives a
real Chromium against Ed's logged-in TradingView session, opens HIS layout (the one with
the TS01 indicator on it) at the symbol and interval of the setup, and saves a PNG. It
also asks TradingView for its own permanent snapshot link (`tradingview.com/x/…`) when it
can get one — that is the link the journal entries already use.

Why a browser profile and not a login script: TradingView's session belongs in a browser,
and a persistent profile means the credentials are never in this repo, never in a config
file and never in an argument. Sign in once, headful, on the server:

    python -m common.charts.tvshot --login          # opens a window; sign in; press Enter

Then, unattended:

    python -m common.charts.tvshot --shot AVAXUSDC
    python -m common.charts.tvshot --shot AVAXUSDC --out C:\tmp\avax.png --interval 15
    python -m common.charts.tvshot --selftest       # proves Playwright works at all

Profile:   %USERPROFILE%\.config\tradingview\profile   (TRADING_CONFIG_DIR respected)
Layout:    config/book.yaml → tradingview.layout_id
Requires:  python -m pip install playwright  &&  python -m playwright install chromium

Nothing here logs in, places an order, or writes to the exchange. It reads a chart.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

CONFIG_DIR = Path(os.environ.get("TRADING_CONFIG_DIR", Path.home() / ".config")) / "tradingview"
PROFILE_DIR = CONFIG_DIR / "profile"
SHOT_DIR = CONFIG_DIR / "shots"
PERMALINK_RE = re.compile(r"https?://(?:www\.)?tradingview\.com/x/[A-Za-z0-9]+/?")
VIEWPORT = {"width": 1600, "height": 900}

# The main chart pane, in order of preference. TradingView renames classes from time to
# time, so this is a list and the last resort is the whole page.
CHART_SELECTORS = ['div[class*="layout__area--center"]', "div.chart-gui-wrapper",
                   "div.chart-container", "div.chart-markup-table"]


class ShotError(RuntimeError):
    pass


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ShotError("playwright is not installed — run:  python -m pip install playwright "
                        "&&  python -m playwright install chromium") from e
    return sync_playwright


def chart_url(cfg: dict, sym: str, interval: str = "15") -> str:
    tv = (cfg or {}).get("tradingview", {}) or {}
    ex, suffix = tv.get("exchange", "BINANCE"), tv.get("suffix", ".P")
    layout = str(tv.get("layout_id", "") or "").strip()
    base = "https://www.tradingview.com/chart/" + (f"{layout}/" if layout else "")
    return f"{base}?symbol={ex}:{sym}{suffix}&interval={interval}"


def out_path(sym: str, when=None) -> Path:
    t = dt.datetime.fromtimestamp(when / 1000, dt.timezone.utc) if when else dt.datetime.now(dt.timezone.utc)
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SHOT_DIR / f"{t:%Y%m%d-%H%M}-{sym}.png"


def png_size(path: Path) -> tuple[int, int] | None:
    """Width and height from the PNG header — a cheap check that we captured a picture."""
    try:
        b = path.open("rb").read(33)
        if b[:8] != b"\x89PNG\r\n\x1a\n" or b[12:16] != b"IHDR":
            return None
        return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
    except Exception:  # noqa: BLE001
        return None


def _dismiss(page) -> None:
    """Promotional dialogs and the 'restore layout' prompt sit on top of the chart."""
    for _ in range(3):
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(250)
        except Exception:  # noqa: BLE001
            break
    for sel in ('button[data-name="close"]', 'button[aria-label="Close"]', "span.close-button"):
        try:
            for b in page.query_selector_all(sel)[:3]:
                if b.is_visible():
                    b.click(timeout=1500)
                    page.wait_for_timeout(250)
        except Exception:  # noqa: BLE001
            pass


def _signed_in(page) -> bool:
    try:
        return not page.query_selector('button[data-name="header-user-menu-sign-in"]')
    except Exception:  # noqa: BLE001
        return True


def _permalink(page, wait_ms: int = 15000) -> str | None:
    """Alt+S is TradingView's own 'take a snapshot' — it mints a permanent /x/ link.
    Found by matching the link's shape anywhere on the page, not by a fragile selector."""
    try:
        page.keyboard.press("Alt+s")
    except Exception:  # noqa: BLE001
        return None
    waited = 0
    while waited < wait_ms:
        page.wait_for_timeout(500)
        waited += 500
        try:
            values = page.eval_on_selector_all(
                "input, textarea", "els => els.map(e => e.value || '')")
            for v in values + [page.inner_text("body")[:20000]]:
                m = PERMALINK_RE.search(v or "")
                if m:
                    return m.group(0)
        except Exception:  # noqa: BLE001
            pass
    return None


def capture(sym: str, cfg: dict | None = None, out: Path | str | None = None, interval: str = "15",
            headless: bool = True, settle: float = 6.0, permalink: bool = True,
            url: str | None = None, when: int | None = None) -> dict:
    """Open the chart and save a PNG. Returns a dict; raises ShotError only on a hard failure
    (no browser, no page). A missing permalink or a logged-out session is reported, not raised."""
    sync_playwright = _playwright()
    target = url or chart_url(cfg or {}, sym, interval)
    png = Path(out) if out else out_path(sym, when)
    png.parent.mkdir(parents=True, exist_ok=True)
    r = {"symbol": sym, "chart_url": target, "png": None, "permalink": None,
         "signed_in": None, "warnings": []}
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=headless, viewport=VIEWPORT,
            args=["--disable-blink-features=AutomationControlled", "--hide-scrollbars"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(60000)
            page.goto(target, wait_until="domcontentloaded", timeout=90000)
            try:
                page.wait_for_selector("canvas", timeout=60000)
            except Exception:  # noqa: BLE001
                r["warnings"].append("no chart canvas appeared — the page may not be a chart")
            page.wait_for_timeout(int(settle * 1000))
            _dismiss(page)
            r["signed_in"] = _signed_in(page)
            if r["signed_in"] is False:
                r["warnings"].append("not signed in to TradingView — run --login on this machine; "
                                     "the layout and its indicators will not be loaded")
            if permalink:
                r["permalink"] = _permalink(page)
                if not r["permalink"]:
                    r["warnings"].append("no permanent /x/ link (Alt+S) — the PNG is still good")
                _dismiss(page)
                page.wait_for_timeout(500)
            shot = None
            for sel in CHART_SELECTORS:
                el = page.query_selector(sel)
                if el:
                    try:
                        el.screenshot(path=str(png))
                        shot = sel
                        break
                    except Exception:  # noqa: BLE001
                        continue
            if not shot:
                page.screenshot(path=str(png), full_page=False)
                r["warnings"].append("chart pane not found by selector — whole viewport captured")
            r["element"] = shot or "viewport"
            r["png"] = str(png)
        finally:
            ctx.close()
    if not png.is_file() or png.stat().st_size < 1000:
        raise ShotError(f"screenshot did not produce a usable file ({png})")
    r["bytes"] = png.stat().st_size
    r["size"] = png_size(png)
    if r["size"] and (r["size"][0] < 400 or r["size"][1] < 300):
        r["warnings"].append(f"image is only {r['size'][0]}x{r['size'][1]} — check the selector")
    return r


def try_capture(sym: str, **kw) -> dict:
    """Fail-soft wrapper for the runner: never raises, reports what went wrong."""
    try:
        return capture(sym, **kw)
    except Exception as e:  # noqa: BLE001
        return {"symbol": sym, "png": None, "permalink": None,
                "error": f"{type(e).__name__}: {str(e)[:200]}"}


def login() -> None:
    """Headful, once per machine: sign in, then press Enter here. The session is kept in the
    browser profile — no TradingView credentials go anywhere near this repo."""
    sync_playwright = _playwright()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False, viewport=VIEWPORT)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.tradingview.com/#signin", wait_until="domcontentloaded")
        print(f"profile: {PROFILE_DIR}")
        print("Sign in to TradingView in the window that opened, open your chart layout once,")
        print("then come back here and press Enter.")
        try:
            input()
        except EOFError:
            pass
        signed = _signed_in(page)
        ctx.close()
    print("signed in — session stored in the profile" if signed else
          "WARNING: still showing a Sign in button; the session may not have been stored")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--login", action="store_true", help="one-time headful sign-in on this machine")
    g.add_argument("--shot", metavar="SYMBOL", help="capture the chart for this symbol")
    g.add_argument("--selftest", action="store_true", help="prove Playwright works, no TradingView")
    ap.add_argument("--out", default=None, help="PNG path (default: .config\\tradingview\\shots\\)")
    ap.add_argument("--interval", default="15")
    ap.add_argument("--headful", action="store_true", help="show the browser (for diagnosing)")
    ap.add_argument("--settle", type=float, default=6.0, help="seconds to let the chart draw")
    ap.add_argument("--no-permalink", action="store_true", help="skip the Alt+S permanent link")
    ap.add_argument("--url", default=None, help=argparse.SUPPRESS)   # test hook
    a = ap.parse_args(argv)
    try:
        if a.login:
            login()
            return 0
        if a.selftest:
            page = "data:text/html,<h1 style='font:48px sans-serif;padding:40px'>tvshot selftest</h1><canvas></canvas>"
            r = capture("SELFTEST", out=a.out or (SHOT_DIR / "selftest.png"), url=page,
                        headless=not a.headful, settle=1.0, permalink=False)
        else:
            from common.reports.trade_file import load_book
            r = capture(a.shot.upper(), cfg=load_book(), out=a.out, interval=a.interval,
                        headless=not a.headful, settle=a.settle, permalink=not a.no_permalink,
                        url=a.url)
    except ShotError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    dims = "x".join(str(v) for v in (r.get("size") or ())) or "?"
    print(f"png:       {r['png']}  ({dims}, {r.get('bytes', 0):,} bytes, {r.get('element')})")
    print(f"chart:     {r['chart_url']}")
    print(f"permalink: {r['permalink'] or '(none)'}")
    print(f"signed in: {r['signed_in']}")
    for w in r["warnings"]:
        print(f"warning:   {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
