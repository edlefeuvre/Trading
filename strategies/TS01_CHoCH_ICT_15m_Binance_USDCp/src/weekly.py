r"""TS01 — the Sunday programme (choch_sizes.py migrated, 2 Sep 2026). Spec: STRATEGY.md §8a.

For every symbol in config/universe.yaml: pull the full 15m archive from data.binance.vision
(cached), run the locked engine, and classify by the tier rule
    1.0  mean net R > 0 in BOTH the prior period and the last 12 months
    0.5  positive in ONE of them
    0    neither, or under 12 months of history
Writes results/weekly/<date>/{r_factors.csv, run.json, summary.md, proposal.json}, sends the
headline table to the Digest topic, files the review into the Sunday folder on Google Drive
(Trading/Weeklies/yyyy-mm-dd Wnn/, summary first, detail below, plus a Google Doc copy for the
phone) and — when any R factor would change — posts an Apply / Hold / Re-run keyboard to the
Approvals topic. It PROPOSES; it never changes universe.yaml by itself.

    python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.weekly                 # run, write, file, send
    python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.weekly --stdout        # run, write, print only
    python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.weekly --run-now       # same as the first, off-schedule
    python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.weekly --apply [--proposal ID]
        rewrite the proposed tiers into universe.yaml, add the change-log row, refresh the filed
        review's Status line, COMMIT (and push if a remote exists). This is what the Apply button runs.
    python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.weekly --hold  [--proposal ID]
    python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.weekly --status
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from common.alerts import telegram
from common.data import binance_klines as data
from common.engine import ict_base as engine

__version__ = "1.9"
HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent
TS = HERE.name.split("_")[0]
FULL, HALF, ZERO = 1.0, 0.5, 0.0
APPLY_CMD = f"python -m strategies.{HERE.name}.src.weekly --apply"


def load_yaml(path: Path):
    try:
        import yaml  # type: ignore
    except ImportError:
        sys.exit("pyyaml is required:  python -m pip install pyyaml")
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def spec_version(params) -> str:
    """STRATEGY.md frontmatter is the version of record; params meta.version is the fallback."""
    m = re.search(r"^version:\s*([0-9.]+)\s*$", (HERE / "STRATEGY.md").read_text(encoding="utf-8"), flags=re.M) \
        if (HERE / "STRATEGY.md").is_file() else None
    return m.group(1) if m else str(params.get("meta", {}).get("version", "?"))


def params_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def classify(bars, k, cut12, lookback_months=12):
    tr = [t for t in engine.build_trades(bars, k=k) if t["disc"]]
    p2 = [t["net"] for t in tr if t["t"] >= cut12]
    p1 = [t["net"] for t in tr if t["t"] < cut12]
    m2 = sum(p2) / len(p2) if p2 else None
    m1 = sum(p1) / len(p1) if p1 else None
    months = (bars[-1]["t"] - bars[0]["t"]) / (1000 * 86400 * 30.44) if bars else 0
    if months < lookback_months or m2 is None:
        return len(tr), len(p2), m1, m2, ZERO, "under 12m history"
    if m1 is None:
        return len(tr), len(p2), m1, m2, ZERO, "no prior period"
    pos = (1 if m2 > 0 else 0) + (1 if m1 > 0 else 0)
    return len(tr), len(p2), m1, m2, [ZERO, HALF, FULL][pos], \
        {2: "positive both", 1: "positive one", 0: "positive neither"}[pos]


# ---------------------------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------------------------
def fr(x):
    return f"{x:+.3f}" if x is not None else "  —  "


def digest_text(rows, changes, meta, min_n) -> str:
    """The Telegram table — unchanged shape since v1.8 so the project mirror can still be made from it."""
    now, k, book, cap = meta["now"], meta["k"], meta["book"], meta["cap"]
    funded = [r for r in rows if r["tier_proposed"] > 0]
    f12 = sum(r["n_12m"] for r in funded)
    lines = [f"PAPER · WEEKLY · {TS}",
             f"{now:%a %d %b %Y %H:%M UTC} · engine k={k} · 12m cutoff {now - dt.timedelta(days=365):%d %b %Y}",
             f"book ${book:,.0f} → ceiling ${cap:,.2f}/trade ({'1% of book' if book * 0.01 > 20 else '$20 floor binds'})", "",
             f"{'sym':<13}{'n':>5}{'12m':>5}{'prior R':>9}{'12m R':>8}{'now':>5}{'new':>5}  rule"]
    for r in rows:
        mark = " <-- CHANGE" if (r["symbol"], r["tier_now"], r["tier_proposed"]) in changes else ""
        prov = "*" if r["provisional"] else ""
        cur = f"{r['tier_now']:g}" if r["tier_now"] is not None else "—"
        lines.append(f"{r['symbol']:<13}{r['n_trades']:>5}{r['n_12m']:>4}{prov:<1}{fr(r['r_prior']):>9}"
                     f"{fr(r['r_12m']):>8}{cur:>5}{r['tier_proposed']:>5g}  {r['rule']}{mark}")
    lines += ["", f"funded {len(funded)} of {len(rows)} · {f12} setups in 12m ≈ {f12 / (365 / 7):.1f}/week"
                  f" · * = under {min_n} trades (provisional)"]
    if changes:
        lines.append(f"{len(changes)} proposed change(s): " + ", ".join(f"{s} {c:g}→{n:g}" for s, c, n in changes))
        lines.append("apply: press Apply in 00 Approvals, or  " + APPLY_CMD + "   (commits with a change-log row)")
    else:
        lines.append("no reallocation proposed this week")
    return "\n".join(lines)


def holdings_block(path: Path) -> list[str]:
    """§8b: what is actually held, from the runner's exchange snapshot. Empty list if nothing."""
    if not path.is_file():
        return []
    try:
        h = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for p in h.get("positions", []) or []:
        out.append(f"- **Position:** {p.get('symbol')} {p.get('side', '')} qty {p.get('qty', '?')} · "
                   f"entry {p.get('entry', '?')} · unrealised {p.get('unrealised_r', '?')}R")
    for o in h.get("orders", []) or []:
        out.append(f"- **Resting:** {o.get('symbol')} {o.get('side', '')} @ {o.get('price', '?')} · "
                   f"window to {o.get('expires', '?')}")
    return out


def summary_prose(rows, changes, min_n) -> list[str]:
    """Generated, short. States what the table says; decides nothing."""
    out = []
    if changes:
        for sym, cur, new in changes:
            r = next(x for x in rows if x["symbol"] == sym)
            tip = r["r_12m"] if new > cur else (r["r_prior"] if r["r_prior"] is not None else r["r_12m"])
            out.append(f"**{sym} {cur:g} → {new:g}** ({r['rule']}). 12m {fr(r['r_12m'])}R on {r['n_12m']}"
                       f"{' — provisional, under ' + str(min_n) if r['provisional'] else ''}; "
                       f"prior period {fr(r['r_prior'])}R. The figure that tips it is {fr(tip)}R"
                       + (" — thin: a handful of trades would flip it." if tip is not None and abs(tip) < 0.1 else "."))
    else:
        out.append("No R factor crosses a tier boundary this week.")
    half = [r for r in rows if r["tier_now"] == HALF]
    imp = [r["symbol"] for r in half if (r["r_prior"] or 0) < 0 < (r["r_12m"] or 0)]
    det = [r["symbol"] for r in half if (r["r_12m"] or 0) < 0 < (r["r_prior"] or 0)]
    if half:
        out.append(f"Of the {len(half)} symbols at 0.5: **{len(imp)} improving** (negative prior, positive 12m: "
                   f"{', '.join(s.replace('USDC', '') for s in imp) or '—'}) and **{len(det)} deteriorating** "
                   f"(positive prior, negative 12m: {', '.join(s.replace('USDC', '') for s in det) or '—'}). "
                   "The tier rule treats both alike by design — it sizes on the sign of two means.")
    prov = [r["symbol"].replace("USDC", "") for r in rows if r["provisional"]]
    if prov:
        out.append(f"Provisional (under {min_n} trades in 12m): {', '.join(prov)}.")
    funded = [r for r in rows if r["tier_proposed"] > 0]
    pos = sum(1 for r in funded if (r["r_12m"] or 0) > 0)
    out.append(f"{pos} of {len(funded)} funded symbols have a positive 12m R.")
    return out


def render_summary(rows, changes, meta, min_n, status: str, holdings: list[str], open_items: list[str],
                   digest: str, proposal_id: str | None) -> str:
    now = meta["now"]
    funded = [r for r in rows if r["tier_proposed"] > 0]
    f12 = sum(r["n_12m"] for r in funded)
    L = [f"# {TS} CHoCH ICT 15m (v{meta['spec_version']}) — Weekly R-factor review, {now:%a %-d %b %Y}", "",
         f"- **Run:** PAPER · WEEKLY · {TS}, {now:%a %d %b %Y %H:%M UTC}, engine k={meta['k']}, "
         f"12-month cutoff {now - dt.timedelta(days=365):%d %b %Y}", "",
         f"- **Book:** ${meta['book']:,.0f} → ceiling ${meta['cap']:,.2f} per trade "
         f"({'1% of book' if meta['book'] * 0.01 > 20 else 'the $20 floor binds'})", "",
         f"- **Universe:** {len(rows)} symbols; {len(funded)} funded (R factor 1 or 0.5), {len(rows) - len(funded)} at 0", "",
         f"- **Activity:** {f12} setups in 12 months ≈ {f12 / (365 / 7):.1f} per week", "",
         f"- **Proposed changes:** {len(changes)}" + (" — " + ", ".join(f"{s} {c:g} → {n:g}" for s, c, n in changes) if changes else ""), "",
         f"- **Status:** {status}", ""]
    if holdings:
        L += ["## Holdings", ""] + [h + "\n" for h in holdings]
    L += ["## Summary", ""]
    for p in summary_prose(rows, changes, min_n):
        L += [p, ""]
    if open_items:
        L += ["**For the Sunday pass (decisions for Ed, not the job):**", ""]
        L += [f"{i}. {x}" for i, x in enumerate(open_items, 1)] + [""]
    L += ["## Detail — R factors by symbol", "",
          "Columns as sent by the job: symbol · n (all trades) · n (12m, * = under "
          f"{min_n}, provisional) · net R/trade prior period · net R/trade 12m · R factor now · R factor proposed · rule.", "",
          "```"]
    body = digest.split("\n\n", 1)[1] if "\n\n" in digest else digest
    L += body.split("\n") + ["```", ""]
    if proposal_id:
        L += [f"- **Proposal id:** `{proposal_id}` (what the Approvals buttons refer to)", ""]
    L += [f"- **Apply with:** `{APPLY_CMD}` (or the Apply button in 00 Approvals)", "",
          "## Original message (verbatim, Telegram · Digest)", "", "```", digest, "```", "",
          f"_Generated by `src/weekly.py` v{__version__} · params {meta['params_hash']} · "
          f"`results/weekly/{now:%Y-%m-%d}/run.json`. Research, not advice._"]
    return "\n".join(L) + "\n"


def set_status_line(md: str, status: str) -> str:
    return re.sub(r"^- \*\*Status:\*\* .*$", f"- **Status:** {status}", md, count=1, flags=re.M)


# ---------------------------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------------------------
def compute(params, uni, symbols, now):
    k = int(params.get("structure", {}).get("pivot_k", engine.K))
    lookback = int(params.get("weekly", {}).get("lookback_months", 12))
    min_n = int(params.get("weekly", {}).get("min_trades_for_r", 30))
    start = tuple(int(x) for x in str(uni.get("dataset_start", "2024-01")).split("-")[:2])
    current = {str(r["symbol"]).upper(): float(r.get("tier", 0) or 0) for r in uni.get("symbols", []) if isinstance(r, dict)}
    cut12 = (now - dt.timedelta(days=365)).timestamp() * 1000
    rows, skipped = [], []
    for sym in symbols:
        try:
            bars = data.history(sym, start=start)
        except Exception as e:  # noqa: BLE001
            skipped.append(f"{sym}: {e}"); continue
        if len(bars) < 5000:
            skipped.append(f"{sym}: only {len(bars)} bars"); continue
        n, n2, m1, m2, tier, why = classify(bars, k, cut12, lookback)
        rows.append(dict(symbol=sym, dataset_start=f"{start[0]}-{start[1]:02d}",
                         dataset_end=dt.datetime.fromtimestamp(bars[-1]["t"] / 1000, dt.timezone.utc).date().isoformat(),
                         bars=len(bars), n_trades=n, n_12m=n2, r_prior=m1, r_12m=m2, tier_now=current.get(sym),
                         tier_proposed=tier, provisional=(n2 < min_n), rule=why))
    rows.sort(key=lambda r: (-r["tier_proposed"], -(r["r_12m"] if r["r_12m"] is not None else -9)))
    return rows, skipped, k, min_n


def run(a) -> int:
    t0 = time.time()
    params = load_yaml(HERE / "config" / "params.yaml")
    uni = load_yaml(HERE / "config" / "universe.yaml")
    book_cfg = load_yaml(REPO / "config" / "book.yaml")
    now = dt.datetime.now(dt.timezone.utc)
    current = [str(r["symbol"]).upper() for r in uni.get("symbols", []) if isinstance(r, dict)]
    symbols = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else current
    print("fetching history...", file=sys.stderr)
    rows, skipped, k, min_n = compute(params, uni, symbols, now)
    for s in skipped:
        print("  " + s, file=sys.stderr)
    book = float(params.get("risk", {}).get("book_usd", 0) or 0)
    meta = dict(now=now, k=k, book=book, cap=max(book * 0.01, float(params.get("risk", {}).get("unit_usd", 20))),
                spec_version=spec_version(params),
                params_hash=params_hash(HERE / "config" / "params.yaml"))
    changes = [(r["symbol"], r["tier_now"], r["tier_proposed"]) for r in rows
               if r["tier_now"] is not None and r["tier_now"] != r["tier_proposed"]]

    out = HERE / "results" / "weekly" / now.strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "r_factors.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["symbol"])
        w.writeheader(); w.writerows(rows)

    # proposal record — the thing a button or a reply refers to
    ttl = int(params.get("weekly", {}).get("approval_ttl_days", 7))
    proposal = None
    if changes:
        ch = [dict(symbol=s, **{"from": c, "to": n}, rule=next(r["rule"] for r in rows if r["symbol"] == s))
              for s, c, n in changes]
        pid = hashlib.sha256(json.dumps([ch, now.strftime("%Y-%m-%d"), meta["params_hash"]], sort_keys=True).encode()).hexdigest()[:12]
        proposal = dict(id=pid, run=now.strftime("%Y-%m-%d"), spec_version=meta["spec_version"],
                        params_hash=meta["params_hash"], changes=ch, book_usd=book, status="proposed",
                        expires=(now + dt.timedelta(days=ttl)).strftime("%Y-%m-%dT%H:%M:%SZ"), approval_message=None)
        (out / "proposal.json").write_text(json.dumps(proposal, indent=1), encoding="utf-8")

    digest = digest_text(rows, changes, meta, min_n)
    status = f"PROPOSED — {len(changes)} change(s) awaiting Ed" if changes else "NO CHANGE PROPOSED"
    open_items = load_yaml(HERE / "results" / "sunday-open-items.yaml").get("items", []) or []
    summary = render_summary(rows, changes, meta, min_n, status, holdings_block(HERE / "results" / "holdings.json"),
                             open_items, digest, proposal["id"] if proposal else None)
    (out / "summary.md").write_text(summary, encoding="utf-8")
    (out / "run.json").write_text(json.dumps(dict(
        weekly_version=__version__, spec_version=meta["spec_version"], params_hash=meta["params_hash"],
        run=now.strftime("%Y-%m-%dT%H:%M:%SZ"), symbols=len(rows), skipped=skipped,
        dataset=[rows[0]["dataset_start"], max(r["dataset_end"] for r in rows)] if rows else None,
        wall_seconds=round(time.time() - t0, 1), proposal=proposal["id"] if proposal else None), indent=1), encoding="utf-8")
    print(digest)

    warnings = []
    filed_url = ""
    if not a.stdout and not a.no_study:
        warnings += run_study()
    if not a.stdout and not a.no_drive:
        url, w = file_to_drive(book_cfg, now, out, summary, proposal, open_items, changes)
        filed_url, warnings = url, warnings + w

    if a.stdout:
        return 0
    al = params.get("alerts", {})
    text = digest + (f"\nreview: {filed_url}" if filed_url else "") + ("".join(f"\n⚠ {w}" for w in warnings))
    try:
        telegram.send(text, to=al.get("weekly_to", "digest"), book=al.get("book", "trading"))
    except telegram.TelegramError as e:
        print(f"telegram failed: {e}", file=sys.stderr)
    if proposal:
        try:
            bot = telegram.Bot("rickyassist_bot", book=al.get("book", "trading"))
            chat, _ = bot.resolve_to(al.get("approvals_to", "approvals"))
            ids = bot.send(approval_text(proposal, rows), to=al.get("approvals_to", "approvals"),
                           buttons=approval_buttons(proposal["id"]))
            proposal["approval_message"] = dict(chat_id=chat, message_id=ids[-1])
            (out / "proposal.json").write_text(json.dumps(proposal, indent=1), encoding="utf-8")
        except telegram.TelegramError as e:
            print(f"approvals message failed: {e}", file=sys.stderr)
    return 0


def run_study() -> list[str]:
    """Refresh the hour-of-day study and the per-setup tranche list so they file with the review.
    The klines are already cached by the run above, so this is cheap. Fail-soft."""
    warns = []
    cmd = [sys.executable, str(REPO / "bin" / "study-hours"), "--strategy", HERE.name,
           "--html", str(HERE / "results" / "study-hours.html"), "--csv", str(HERE / "results" / "tranche-setups.csv")]
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            warns.append(f"study-hours failed: {(r.stderr or r.stdout).strip()[-200:]}")
    except Exception as e:  # noqa: BLE001
        warns.append(f"study-hours not run: {e}")
    return warns


def approval_text(proposal, rows=None) -> str:
    run = dt.datetime.strptime(proposal["run"], "%Y-%m-%d")
    exp = dt.datetime.strptime(proposal["expires"], "%Y-%m-%dT%H:%M:%SZ")
    L = [f"PAPER · APPROVAL · {TS} · R factors {run:%d %b %Y}"]
    for c in proposal["changes"]:
        detail = ""
        if rows:
            r = next((x for x in rows if x["symbol"] == c["symbol"]), None)
            if r:
                detail = f"  (12m {fr(r['r_12m'])}R on {r['n_12m']}{'*' if r['provisional'] else ''}, prior {fr(r['r_prior'])}R)"
        L.append(f"{c['symbol']} {c['from']:g} → {c['to']:g}  · {c['rule']}{detail}")
    L += [f"Applies to config/universe.yaml only. Expires {exp:%a %d %b %H:%M} UTC.",
          f"id {proposal['id']} · reply 'approved' or 'hold' also works"]
    return "\n".join(L)


def approval_buttons(pid: str):
    return [[("✅ Apply", f"{TS.lower()}:apply:{pid}"), ("⏸ Hold", f"{TS.lower()}:hold:{pid}")],
            [("🔄 Re-run", f"{TS.lower()}:rerun")]]


def file_to_drive(book_cfg, now, out: Path, summary: str, proposal, open_items, changes):
    """The Sunday folder. Returns (url of the review doc or folder, warnings)."""
    from common.drive.files import Drive, DriveError
    from common.reports import weekly_folder as wf
    dcfg = book_cfg.get("drive", {}) or {}
    if not dcfg.get("enabled", True):
        return "", []
    weeklies = dcfg.get("weeklies_folder")
    if not weeklies:
        return "", ["Drive: drive.weeklies_folder not set in config/book.yaml"]
    pattern = dcfg.get("week_folder", "{sunday:%Y-%m-%d} W{iso_week:02d}")
    drive = Drive()
    items = [wf.Item(f"01 - {TS} weekly R-factor review.md", summary, as_doc=True,
                     line=f"PAPER · WEEKLY · {TS} run of {now:%H:%M} UTC; {len(changes)} proposed change(s)"
                          + (": " + ", ".join(f"{s} {c:g} → {n:g}" for s, c, n in changes) if changes else "")),
             wf.Item(f"01 - {TS} weekly r_factors.csv", (out / "r_factors.csv").read_bytes(), line="the table as data")]
    extras = [(HERE / "results" / "study-hours.html", "03 - study-hours.html", "hour-of-day / 3h-tranche study (7-day × 8-block grid)"),
              (HERE / "results" / "trade-reports" / f"{TS}-paper-track.csv", "04 - paper-track.csv", "paper-track register (every setup, traded or not)"),
              (HERE / "results" / "tranche-setups.csv", "05 - tranche-setups.csv", "one row per filled setup: UTC day, 3h block, symbol, side, R, pool R")]
    for src, name, line in extras:
        if src.is_file():
            items.append(wf.Item(name, src.read_bytes(), line=line))
    try:
        filed = wf.file_week(drive, weeklies, now.date(), items, pattern)
        decisions = []
        opens = ([f"{c[0]} {c[1]:g} → {c[2]:g} — Apply or Hold (proposal {proposal['id']})" for c in changes]
                 if proposal else []) + list(open_items)
        index = wf.render_index(now.date(), filed, decisions, opens, pattern, f"src/weekly.py v{__version__}")
        drive.upsert_doc(f"00 - Sunday review {wf.week_folder_name(now.date(), pattern)} — index", filed.folder["id"], index)
        (out / "drive.json").write_text(json.dumps(dict(folder=filed.folder, items=[
            dict(name=i.name, url=i.url, doc_url=i.doc_url) for i in filed.items]), indent=1), encoding="utf-8")
        url = next((i.doc_url for i in filed.items if i.doc_url), filed.folder["url"])
        return url, [f"Drive: {e}" for e in filed.errors]
    except DriveError as e:
        return "", [f"Drive filing failed: {e}"]


# ---------------------------------------------------------------------------------------------
# apply / hold — what the Approvals buttons run
# ---------------------------------------------------------------------------------------------
def latest_proposal(pid: str | None) -> tuple[Path, dict] | tuple[None, None]:
    files = sorted((HERE / "results" / "weekly").glob("*/proposal.json"), reverse=True)
    for p in files:
        d = json.loads(p.read_text(encoding="utf-8"))
        if pid is None or d.get("id") == pid:
            return p, d
    return None, None


def bump_version(v: str) -> str:
    major, _, minor = str(v).partition(".")
    return f"{major}.{int(minor or 0) + 1}"


def add_changelog_row(doc: Path, section: str, change: str, files: str, today: str) -> str:
    """Append a row under '## Change log' (newest first) and bump the frontmatter version. Returns new version."""
    txt = doc.read_text(encoding="utf-8")
    m = re.search(r"^version:\s*([0-9.]+)\s*$", txt, flags=re.M)
    if not m:
        raise RuntimeError("STRATEGY.md has no version: line")
    new = bump_version(m.group(1))
    txt = txt[:m.start()] + f"version: {new}" + txt[m.end():]
    head = re.search(r"^\| Date \| Version \| Section \| Change \| Files \|\n\|[-| ]+\|\n", txt, flags=re.M)
    if not head:
        raise RuntimeError("STRATEGY.md change-log header not found")
    row = f"| {today} | {new} | {section} | {change} | {files} |\n"
    txt = txt[:head.end()] + row + txt[head.end():]
    doc.write_text(txt, encoding="utf-8")
    return new


def rewrite_universe(path: Path, changes: list[dict], today: str) -> Path:
    """Rewrite tiers on a COPY; the caller moves it in last so a failure leaves the original untouched."""
    txt = path.read_text(encoding="utf-8")
    for c in changes:
        sym, new, why = c["symbol"], float(c["to"]), c.get("rule", "")
        txt, n = re.subn(rf"(\{{symbol: {re.escape(sym)},\s*tier: )[0-9.]+(,\s*why: )[^}}]*",
                         rf"\g<1>{new:g}\g<2>{why} ({today})", txt)
        if n != 1:
            raise RuntimeError(f"could not find {sym} in universe.yaml")
    tmp = path.with_suffix(".yaml.new")
    tmp.write_text(txt, encoding="utf-8")
    return tmp


def git(*args, check=True) -> str:
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def edit_approval_message(proposal, text, params):
    msg = proposal.get("approval_message")
    if not msg:
        return
    try:
        al = params.get("alerts", {})
        telegram.Bot("rickyassist_bot", book=al.get("book", "trading")).edit(msg["chat_id"], msg["message_id"], text)
    except telegram.TelegramError as e:
        print(f"could not edit approval message: {e}", file=sys.stderr)


def refile_summary(pfile: Path, status: str, params, book_cfg):
    """Rewrite the Status line in summary.md and, fail-soft, push it back to the Sunday folder."""
    sm = pfile.parent / "summary.md"
    if not sm.is_file():
        return
    md = set_status_line(sm.read_text(encoding="utf-8"), status)
    sm.write_text(md, encoding="utf-8")
    dj = pfile.parent / "drive.json"
    if not dj.is_file():
        return
    try:
        from common.drive.files import Drive, DriveError
        folder = json.loads(dj.read_text(encoding="utf-8"))["folder"]["id"]
        d = Drive()
        name = f"01 - {TS} weekly R-factor review"
        d.upsert_file(name + ".md", folder, md, "text/markdown")
        d.upsert_doc(name, folder, md)
    except Exception as e:  # noqa: BLE001
        print(f"Drive refile skipped: {e}", file=sys.stderr)


def apply(a) -> int:
    params = load_yaml(HERE / "config" / "params.yaml")
    book_cfg = load_yaml(REPO / "config" / "book.yaml")
    pfile, prop = latest_proposal(a.proposal)
    if not prop:
        print(f"NOT APPLIED: no proposal{' ' + a.proposal if a.proposal else ''} found"); return 1
    now = dt.datetime.now(dt.timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if prop.get("status") == "applied":
        print(f"ALREADY APPLIED: {prop['id']} at {prop.get('applied_at')} · {prop.get('commit_subject', '')}"); return 0
    if now > dt.datetime.strptime(prop["expires"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc):
        print(f"NOT APPLIED: proposal {prop['id']} expired {prop['expires']} — run the weekly again"); return 1
    ph = params_hash(HERE / "config" / "params.yaml")
    if prop["params_hash"] != ph:
        print(f"NOT APPLIED: params.yaml changed since the proposal ({prop['params_hash']} → {ph}) — run the weekly again"); return 1
    if a.hold:
        prop.update(status="held", held_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        pfile.write_text(json.dumps(prop, indent=1), encoding="utf-8")
        refile_summary(pfile, f"HELD {today} — current factors stand until the next run", params, book_cfg)
        edit_approval_message(prop, approval_text(prop) + f"\n\n⏸ HELD {now:%d %b %H:%M} UTC — current factors stand until next Sunday", params)
        print(f"HELD: {prop['id']}"); return 0

    # ---- apply, all or nothing --------------------------------------------------------
    uni = HERE / "config" / "universe.yaml"
    doc = HERE / "STRATEGY.md"
    if git("status", "--porcelain", "--", str(uni), str(doc), check=False).strip():
        print("NOT APPLIED: universe.yaml or STRATEGY.md has uncommitted changes — commit or stash them first"); return 1
    backup_doc = doc.read_text(encoding="utf-8")
    try:
        tmp = rewrite_universe(uni, prop["changes"], today)
        desc = ", ".join(f"{c['symbol']} {c['from']:g}→{c['to']:g}" for c in prop["changes"])
        version = add_changelog_row(doc, "§9a", f"R factors applied from the weekly run of {prop['run']} "
                                   f"(proposal {prop['id']}): {desc}. Applied from Telegram by Ed; the job itself changed nothing.",
                                   "`config/universe.yaml`, `STRATEGY.md`", today)
        shutil.move(str(tmp), str(uni))
        cov = HERE / "results" / "coverage.csv"
        newfile = not cov.is_file()
        with open(cov, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if newfile:
                w.writerow(["date", "run", "proposal", "symbol", "from", "to", "rule"])
            for c in prop["changes"]:
                w.writerow([today, prop["run"], prop["id"], c["symbol"], c["from"], c["to"], c.get("rule", "")])
        subject = f"{TS} v{version}: apply R factors {prop['run']} ({prop['id']}) — {desc}"
        prop.update(status="applied", applied_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"), version=version, commit_subject=subject)
        pfile.write_text(json.dumps(prop, indent=1), encoding="utf-8")
        refile_summary(pfile, f"APPLIED {today} — {desc} (STRATEGY.md v{version})", params, book_cfg)
        git("add", "--", str(uni), str(doc), str(cov), str(pfile.parent))
        git("commit", "-q", "-m", subject)
        sha = git("rev-parse", "--short", "HEAD")      # the sha cannot live inside its own commit; find it by subject
        pushed = ""
        if git("remote", check=False).strip():
            try:
                git("push"); pushed = " · pushed"
            except RuntimeError as e:
                pushed = f" · push failed ({e})"
        edit_approval_message(prop, approval_text(prop) + f"\n\n✅ APPLIED {now:%d %b %H:%M} UTC · {sha}{pushed}\n"
                              "the runner picks the new factors up on its next 15-minute cycle", params)
        print(f"APPLIED: {desc} · {TS} v{version} · commit {sha}{pushed}")
        return 0
    except Exception as e:  # noqa: BLE001
        doc.write_text(backup_doc, encoding="utf-8")
        for p in (uni.with_suffix(".yaml.new"),):
            if p.exists():
                p.unlink()
        print(f"NOT APPLIED: {e} — universe.yaml untouched")
        return 1


def status(a) -> int:
    pfile, prop = latest_proposal(a.proposal)
    if not prop:
        print("no proposals on file"); return 0
    print(json.dumps(prop, indent=1)); return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stdout", action="store_true", help="print, do not send or file")
    ap.add_argument("--run-now", action="store_true", help="run off-schedule (same as no flag; here for the Re-run button)")
    ap.add_argument("--no-drive", action="store_true", help="skip the Google Drive filing for this run")
    ap.add_argument("--no-study", action="store_true", help="do not refresh study-hours.html / tranche-setups.csv")
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--apply", action="store_true", help="apply the latest (or --proposal ID) proposal: universe.yaml, change-log row, commit")
    ap.add_argument("--hold", action="store_true", help="mark the proposal HELD; nothing changes")
    ap.add_argument("--proposal", default=None, help="proposal id (default: the most recent)")
    ap.add_argument("--status", action="store_true", help="print the latest proposal record")
    a = ap.parse_args(argv)
    if a.status:
        return status(a)
    if a.apply or a.hold:
        return apply(a)
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
