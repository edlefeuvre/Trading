r"""common.reports.trade_file — one living Google Doc per setup.

Created at SETUP, updated at every lifecycle event, closed off when the 32-bar window ends.
The Doc's id and URL never change, so the link posted to Telegram at SETUP still resolves
after the close. Ed's own writing lives below `## My notes` and is spliced back in on every
rewrite, so a 03:00 update never destroys what he typed on the phone.

Filename carries NO status — `20260906-1430-TS01-AVAXUSDC-SELL` — precisely because status
changes over the life of the setup and a rename would break every link already sent. Status
lives inside the document and in the register.

Config (config/book.yaml):
    drive:
      enabled: true
      trade_reports_folder: <folder id>
    tradingview:
      layout_id: ""          # from your chart URL; blank falls back to a plain symbol chart
      exchange: BINANCE
      suffix: ".P"

    python -m common.reports.trade_file --demo <folder_id>    # build and publish a sample

Nothing here places an order or reads an exchange key.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

TZ = dt.timezone.utc
LOCAL_OFFSET_H = 2                      # Gibraltar; display only
NOTES_MARKER = "## My notes"
NOTES_PLACEHOLDER = ("_Anything you write below this line is kept forever — the runner rewrites "
                     "everything above it and never touches this section._")

OPEN, CLOSED_TRADED, CLOSED_PAPER = "OPEN", "CLOSED (Traded)", "CLOSED (Paper)"

SNAP_PLACEHOLDER = "_paste your `tradingview.com/x/…` link here_"
SNAP_RE = re.compile(r"https?://(?:www\.)?tradingview\.com/x/[A-Za-z0-9]+/?")


def load_book(repo: Path | None = None) -> dict:
    """config/book.yaml — the drive and tradingview settings. Never raises; {} if unreadable."""
    try:
        import yaml  # type: ignore
        p = (repo or REPO) / "config" / "book.yaml"
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        return {}


def _utc(ms) -> str:
    return dt.datetime.fromtimestamp(int(ms) / 1000, TZ).strftime("%a %d %b %Y %H:%M UTC")


def _local(ms) -> str:
    return (dt.datetime.fromtimestamp(int(ms) / 1000, TZ)
            + dt.timedelta(hours=LOCAL_OFFSET_H)).strftime("%H:%M")


def doc_name(ts_id: str, sym: str, side: str, t_placed) -> str:
    """Stable for the life of the setup — no status, so the link never breaks."""
    t = dt.datetime.fromtimestamp(int(t_placed) / 1000, TZ) + dt.timedelta(hours=LOCAL_OFFSET_H)
    return f"{t:%Y%m%d-%H%M}-{ts_id}-{sym}-{side}"


def chart_urls(cfg: dict, sym: str, tf: str = "15m") -> tuple[str, str]:
    tv = (cfg or {}).get("tradingview", {}) or {}
    ex = tv.get("exchange", "BINANCE")
    suffix = tv.get("suffix", ".P")
    layout = str(tv.get("layout_id", "") or "").strip()
    iv = tf.replace("m", "")
    base = f"https://www.tradingview.com/chart/"
    if layout:
        base += f"{layout}/"
    return f"{base}?symbol={ex}:{sym}{suffix}&interval={iv}", f"{ex}:{sym}{suffix}"


def build(ts_id: str, sym: str, side: str, mode: str, status: str, ticket_lines: list[str],
          t_placed, expires_ms, events: list, exchange_line: str, cfg: dict,
          outcome: str = "", tf: str = "15m", snapshot: str = "") -> str:
    """The runner-owned half of the document. `## My notes` is appended empty; the Drive
    client splices Ed's real notes in on update."""
    word = "short" if side.upper() == "SELL" else "long"
    live, tvsym = chart_urls(cfg, sym, tf)
    L = [f"# {sym} · {side.upper()} ({word}) · {ts_id} · {mode} · {status}", ""]
    if status == OPEN:
        L.append(f"**Open.** Window closes {_utc(expires_ms)} ({_local(expires_ms)} local).")
    else:
        L.append(f"**{status}.** {outcome}" if outcome else f"**{status}.**")
    L += ["", f"Setup bar (FVG): {_utc(t_placed)} ({_local(t_placed)} local)", "",
          "## Ticket", ""]
    L += [f"- {ln}" for ln in ticket_lines if ln.strip()]
    L += ["", "## Chart", "",
          f"- Live chart, your layout: {live}",
          f"- Snapshot: {snapshot}" if snapshot else
          f"- Snapshot: {SNAP_PLACEHOLDER}",
          "", "## Lifecycle", "",
          "| When (UTC) | Event | Detail |", "|---|---|---|"]
    for e in events:
        when, ev, detail = (list(e) + ["", "", ""])[:3]
        L.append(f"| {when} | {ev} | {detail} |")
    L += ["", "## Exchange", "",
          f"{exchange_line or 'not checked'}", "",
          "_What the runner could see against this ticket at the last update. In Paper mode the "
          "runner places nothing; anything here is an order you placed by hand._",
          "", NOTES_MARKER, "", NOTES_PLACEHOLDER, ""]
    return "\n".join(L)


def splice(new_md: str, old_md: str) -> str:
    """Carry the human half of the old document into the new one: Ed's notes, and the
    TradingView snapshot link if he pasted one and the runner has none of its own."""
    if not old_md:
        return new_md
    unescape = lambda t: re.sub(r"\\([-_*#\[\]()`>+.!~|%$&])", r"\1", t)   # noqa: E731 — Docs' md export escapes punctuation
    i = old_md.find(NOTES_MARKER)
    notes = unescape(old_md[i + len(NOTES_MARKER):]).strip() if i >= 0 else ""
    if notes:
        head = new_md.split(NOTES_MARKER)[0].rstrip()
        new_md = f"{head}\n\n{NOTES_MARKER}\n\n{notes}\n"
    if SNAP_PLACEHOLDER in new_md:
        prior = SNAP_RE.search(unescape(old_md[:i] if i >= 0 else old_md))
        if prior:
            new_md = new_md.replace(SNAP_PLACEHOLDER, prior.group(0))
    return new_md


def publish(cfg: dict, name: str, markdown: str, file_id: str | None = None):
    """Create or update. Returns (file_id, url, error). Never raises — a Drive outage must
    not stop the runner from issuing tickets."""
    d = (cfg or {}).get("drive", {}) or {}
    if not d.get("enabled", False):
        return file_id, None, "drive disabled in book.yaml"
    folder = str(d.get("trade_reports_folder", "") or "").strip()
    if not folder:
        return file_id, None, "drive.trade_reports_folder not set"
    try:
        from common.drive import gdocs
        c = gdocs.Client()
        if file_id is None:
            found = c.find(name, folder)
            file_id = found["id"] if found else None
        if file_id is None:
            r = c.create(name, markdown, folder)
        else:
            try:
                old_md = c.export_md(file_id)
            except Exception:  # noqa: BLE001 — a failed read must not lose the update
                old_md = ""
            r = c.update(file_id, splice(markdown, old_md))
        return r["id"], r.get("webViewLink"), None
    except Exception as e:  # noqa: BLE001 — fail soft, always
        return file_id, None, f"{type(e).__name__}: {str(e)[:160]}"


def sync(cfg: dict, rec: dict, event: str = "", detail: str = "", when: str = "",
         status: str = "", outcome: str = "", exchange_line: str = "", mode: str = "Paper"):
    """Append one lifecycle event to a setup's record and rewrite its Doc.

    `rec` is the runner's state record and is mutated in place: `events`, `status`,
    `report_id`, `report_url`. Returns the URL (or None). Never raises. The document is
    keyed on the setup, so the same record updates the same Doc for its whole life.
    """
    evs = rec.setdefault("events", [])
    if event:
        row = [when or _utc(dt.datetime.now(TZ).timestamp() * 1000), event, detail]
        if not any(list(e)[:2] == row[:2] for e in evs):
            evs.append(row)
    if status:
        rec["status"] = status
    md = build(rec.get("ts", "TS01"), rec["sym"], rec["side"], mode, rec.get("status", OPEN),
               rec.get("ticket", []), rec["t"], rec.get("expires", rec["t"]), evs,
               exchange_line or rec.get("exchange_line", ""), cfg, outcome=outcome)
    if exchange_line:
        rec["exchange_line"] = exchange_line
    name = doc_name(rec.get("ts", "TS01"), rec["sym"], rec["side"], rec["t"])
    fid, url, err = publish(cfg, name, md, rec.get("report_id"))
    if fid:
        rec["report_id"] = fid
    if url:
        rec["report_url"] = url
    rec["report_error"] = err
    return rec.get("report_url")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", metavar="FOLDER_ID", required=True)
    ap.add_argument("--layout", default="", help="override config/book.yaml tradingview.layout_id")
    ap.add_argument("--closed", action="store_true", help="render the closed-off version instead")
    a = ap.parse_args(argv)

    # A FIXED setup time, so the document name is stable and re-running UPDATES the same Doc
    # instead of creating a new one. That is the whole point of the demo.
    today = dt.datetime.now(TZ).date()
    t_placed = int(dt.datetime.combine(today, dt.time(14, 30), TZ).timestamp() * 1000)
    expires = t_placed + 32 * 15 * 60 * 1000
    book = load_book()
    tv = dict(book.get("tradingview", {}) or {})
    if a.layout:
        tv["layout_id"] = a.layout                      # explicit flag wins over book.yaml
    tv.setdefault("exchange", "BINANCE")
    tv.setdefault("suffix", ".P")
    cfg = {"drive": {"enabled": True, "trade_reports_folder": a.demo}, "tradingview": tv}
    ticket = ["Price:   7.626  (limit, maker, post-only)",
              "Size:    123.45 AVAX",
              "TProfit: 7.625  (trigger, mark)",
              "TProfit: 7.592  (price)",
              "StopL:   7.707  (1.06%, mark → market)",
              "Notional: $941",
              "R: 0.5xCaR = $10.00",
              "Pool: 0.43 R  [!] pool below 1R — needs a 71% win rate to break even"]
    events = [(_utc(t_placed), "SETUP", "ticket issued, nothing placed")]
    status, outcome = OPEN, ""
    if a.closed:
        events += [(_utc(t_placed + 3600000), "FILLED (paper)", "touched 7.626"),
                   (_utc(t_placed + 7200000), "STOPPED (paper)", "-1.04 R, taker fee included"),
                   (_utc(expires), "WINDOW CLOSED", "32 bars from the FVG bar")]
        status, outcome = CLOSED_PAPER, "Stopped at −1.04 R on the paper record. No order reached the exchange."
    md = build("TS01", "AVAXUSDC", "SELL", "Paper", status, ticket, t_placed, expires, events,
               "nothing in AVAXUSDC (paper only)", cfg, outcome)
    name = doc_name("TS01", "AVAXUSDC", "SELL", t_placed) + " (demo)"
    fid, url, err = publish(cfg, name, md)
    print(md)
    print("-" * 70)
    if err:
        print(f"NOT PUBLISHED: {err}", file=sys.stderr)
        return 1
    print(f"published: {name}\n{url}")
    print("\nType something under 'My notes' in that Doc, then run this again with --closed.")
    print("Same name, same document: the heading and lifecycle change, your text survives.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
