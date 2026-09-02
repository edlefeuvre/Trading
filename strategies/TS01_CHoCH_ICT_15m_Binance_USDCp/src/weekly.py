r"""TS01 — the Sunday programme (choch_sizes.py migrated, 2 Sep 2026). Spec: STRATEGY.md §8a.

For every symbol in config/universe.yaml: pull the full 15m archive from data.binance.vision
(cached), run the locked engine, and classify by the tier rule
    1.0  mean net R > 0 in BOTH the prior period and the last 12 months
    0.5  positive in ONE of them
    0    neither, or under 12 months of history
Writes results/weekly/<date>/r_factors.csv and summary.md, diffs against the current tiers,
and sends the summary to the Digest topic. It PROPOSES; it never changes universe.yaml by
itself. `--apply` rewrites the tiers in universe.yaml for Ed, who then commits with a
change-log row (the hook insists).

    python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.weekly            # run, write, send
    python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.weekly --stdout   # run, write, print only
    python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.weekly --apply    # also write tiers into universe.yaml
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from pathlib import Path

from common.alerts import telegram
from common.data import binance_klines as data
from common.engine import ict_base as engine

__version__ = "1.8"
HERE = Path(__file__).resolve().parent.parent
TS = HERE.name.split("_")[0]
FULL, HALF, ZERO = 1.0, 0.5, 0.0


def load_yaml(path: Path):
    try:
        import yaml  # type: ignore
    except ImportError:
        sys.exit("pyyaml is required:  python -m pip install pyyaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stdout", action="store_true", help="print, do not send to Telegram")
    ap.add_argument("--apply", action="store_true", help="write the proposed tiers into config/universe.yaml")
    ap.add_argument("--symbols", default=None)
    a = ap.parse_args(argv)

    params = load_yaml(HERE / "config" / "params.yaml")
    uni = load_yaml(HERE / "config" / "universe.yaml")
    k = int(params.get("structure", {}).get("pivot_k", engine.K))
    lookback = int(params.get("weekly", {}).get("lookback_months", 12))
    min_n = int(params.get("weekly", {}).get("min_trades_for_r", 30))
    book = float(params.get("risk", {}).get("book_usd", 0) or 0)
    cap = max(book * 0.01, float(params.get("risk", {}).get("unit_usd", 20)))
    start = tuple(int(x) for x in str(uni.get("dataset_start", "2024-01")).split("-")[:2])
    current = {str(r["symbol"]).upper(): float(r.get("tier", 0) or 0) for r in uni.get("symbols", []) if isinstance(r, dict)}
    symbols = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else list(current)

    now = dt.datetime.now(dt.timezone.utc)
    cut12 = (now - dt.timedelta(days=365)).timestamp() * 1000
    print("fetching history...", file=sys.stderr)
    rows = []
    for sym in symbols:
        try:
            bars = data.history(sym, start=start)
        except Exception as e:  # noqa: BLE001
            print(f"  {sym}: {e}", file=sys.stderr); continue
        if len(bars) < 5000:
            print(f"  {sym}: only {len(bars)} bars, skipping", file=sys.stderr); continue
        n, n2, m1, m2, tier, why = classify(bars, k, cut12, lookback)
        rows.append(dict(symbol=sym, dataset_start=f"{start[0]}-{start[1]:02d}",
                         dataset_end=dt.datetime.fromtimestamp(bars[-1]["t"] / 1000, dt.timezone.utc).date().isoformat(),
                         bars=len(bars), n_trades=n, n_12m=n2, r_prior=m1, r_12m=m2, tier_now=current.get(sym),
                         tier_proposed=tier, provisional=(n2 < min_n), rule=why))
    rows.sort(key=lambda r: (-r["tier_proposed"], -(r["r_12m"] if r["r_12m"] is not None else -9)))

    # ---- write results ----
    out = HERE / "results" / "weekly" / now.strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "r_factors.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["symbol"])
        w.writeheader(); w.writerows(rows)

    changes = [(r["symbol"], r["tier_now"], r["tier_proposed"]) for r in rows
               if r["tier_now"] is not None and r["tier_now"] != r["tier_proposed"]]
    funded = [r for r in rows if r["tier_proposed"] > 0]
    f12 = sum(r["n_12m"] for r in funded)

    def fr(x): return f"{x:+.3f}" if x is not None else "  —  "
    lines = [f"PAPER · WEEKLY · {TS}", f"{now:%a %d %b %Y %H:%M UTC} · engine k={k} · 12m cutoff {now - dt.timedelta(days=365):%d %b %Y}",
             f"book ${book:,.0f} → ceiling ${cap:,.2f}/trade ({'1% of book' if book * 0.01 > 20 else '$20 floor binds'})", "",
             f"{'sym':<13}{'n':>5}{'12m':>5}{'prior R':>9}{'12m R':>8}{'now':>5}{'new':>5}  rule"]
    for r in rows:
        mark = " <-- CHANGE" if (r["symbol"], r["tier_now"], r["tier_proposed"]) in changes else ""
        prov = "*" if r["provisional"] else ""
        cur = f"{r['tier_now']:g}" if r["tier_now"] is not None else "—"
        lines.append(f"{r['symbol']:<13}{r['n_trades']:>5}{r['n_12m']:>4}{prov:<1}{fr(r['r_prior']):>9}{fr(r['r_12m']):>8}{cur:>5}{r['tier_proposed']:>5g}  {r['rule']}{mark}")
    lines += ["", f"funded {len(funded)} of {len(rows)} · {f12} setups in 12m ≈ {f12 / (365 / 7):.1f}/week · * = under {min_n} trades (provisional)"]
    if changes:
        lines.append(f"{len(changes)} proposed change(s): " + ", ".join(f"{s} {c:g}→{n:g}" for s, c, n in changes))
        lines.append("apply with:  python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.weekly --apply   (then commit with a change-log row)")
    else:
        lines.append("no reallocation proposed this week")
    summary = "\n".join(lines)
    (out / "summary.md").write_text("```\n" + summary + "\n```\n", encoding="utf-8")
    print(summary)

    if not a.stdout:
        al = params.get("alerts", {})
        try:
            telegram.send(summary, to=al.get("weekly_to", "digest"), book=al.get("book", "trading"))
        except telegram.TelegramError as e:
            print(f"telegram failed: {e}", file=sys.stderr)

    if a.apply and changes:
        p = HERE / "config" / "universe.yaml"
        txt = p.read_text(encoding="utf-8")
        why = {r["symbol"]: r["rule"] for r in rows}
        for sym, _, new in changes:
            txt, n = re.subn(rf"(\{{symbol: {re.escape(sym)},\s*tier: )[0-9.]+(,\s*why: )[^}}]*",
                             rf"\g<1>{new:g}\g<2>{why[sym]} ({now:%Y-%m-%d})", txt)
            if n != 1:
                print(f"could not update {sym} in universe.yaml — edit by hand", file=sys.stderr)
        p.write_text(txt, encoding="utf-8")
        print(f"\nuniverse.yaml updated for {len(changes)} symbol(s). Now: add a change-log row to STRATEGY.md, bump the version, commit.")
    elif a.apply:
        print("\nnothing to apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
