r"""TS04 Breakout Qulla 1D — backtest.

Implements STRATEGY.md §2 on daily bars. Signal on the close of bar i, entry at
the open of bar i+1 (taker). Stop = low of the breakout bar, rejected if wider
than adr_cap × ADR(adr_bars). Half off at +partial_r (maker limit) or at the
close of the partial_bars-th bar if in profit; stop to entry after the partial.
Trail: close below SMA(trail_ma) exits what is left (whole position once
partial_bars have passed). Long only; BTC SMA(fast) > SMA(slow) at the signal close.

Data: Binance USD-M archive (data.binance.vision), USDT perps for history before
the USDC listings (Jan 2024). Funding from the same archive, real prints.

    python -m strategies.TS04_Breakout_Qulla_1D_Binance_USDCp.src.backtest [--trail 20] [--base 14 56]
"""
from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import gzip
import io
import json
import math
import pickle
import statistics
import sys
import urllib.request
import zipfile
from pathlib import Path

__version__ = "0.1"

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from common.data.binance_klines import history, ARCHIVE, DEFAULT_CACHE  # noqa: E402

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None


# ------------------------------------------------------------ params ----
def load_params() -> dict:
    p = HERE.parent / "config" / "params.yaml"
    if yaml:
        return yaml.safe_load(open(p)) or {}
    out, sec = {}, None
    for raw in open(p):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        ind = len(line) - len(line.lstrip())
        k, _, v = line.strip().partition(":")
        v = v.strip()
        if ind == 0 and not v:
            sec = k; out[sec] = {}
        elif ind == 0:
            out[k] = v
        else:
            try:
                v = float(v) if "." in v else int(v)
            except ValueError:
                pass
            out[sec][k] = v
    return out


# ----------------------------------------------------------- funding ----
def funding_month(sym: str, y: int, m: int, cache: Path = DEFAULT_CACHE) -> list[tuple[int, float]]:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{sym}-funding-{y}-{m:02d}.pkl.gz"
    if path.exists():
        with gzip.open(path, "rb") as f:
            return pickle.load(f)
    url = f"{ARCHIVE}/monthly/fundingRate/{sym}/{sym}-fundingRate-{y}-{m:02d}.zip"
    out = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "trading-server/0.1"})
        blob = urllib.request.urlopen(req, timeout=90).read()
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for row in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), "utf-8")):
                if not row or not row[0].strip().isdigit():
                    continue
                t = int(row[0]); t = t // 1000 if t > 1e14 else t
                out.append((t, float(row[-1])))
    except Exception:  # noqa: BLE001
        out = []
    with gzip.open(path, "wb") as f:
        pickle.dump(out, f)
    return out


def funding_history(sym: str, start: tuple[int, int]) -> list[tuple[int, float]]:
    today = dt.datetime.now(dt.timezone.utc).date()
    y, m = start
    out = []
    while (y, m) < (today.year, today.month):
        out += funding_month(sym, y, m)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    out.sort()
    return out


def funding_between(fund: list[tuple[int, float]], ts: list[int], t0: int, t1: int) -> float:
    """Sum of funding rates with t0 < calc_time <= t1 (a long pays positive)."""
    i = bisect.bisect_right(ts, t0); j = bisect.bisect_right(ts, t1)
    return sum(f[1] for f in fund[i:j])


# ------------------------------------------------------------ engine ----
def sma(vals: list[float], n: int, i: int) -> float | None:
    if i + 1 < n:
        return None
    return sum(vals[i - n + 1:i + 1]) / n


def run(bars: list[dict], btc: list[dict], fund: list[tuple[int, float]], P: dict,
        trail_ma: int, base_min: int, base_max: int, taker: float, maker: float, slip: float) -> list[dict]:
    S, ST, X, F = P["setup"], P["stop"], P["exit"], P["filter"]
    c = [b["c"] for b in bars]; h = [b["h"] for b in bars]; l = [b["l"] for b in bars]; o = [b["o"] for b in bars]
    bt = {b["t"]: b["c"] for b in btc}
    btc_c = [bt.get(b["t"]) for b in bars]
    fts = [f[0] for f in fund]
    DAY = 86_400_000
    trades, last_base_start = [], -1
    n = len(bars)
    i = max(S["prior_move_bars_max"], base_max, ST["adr_bars"], F["ma_slow"]) + 1
    while i < n - 1:
        # ---- market filter on BTC at the signal close
        win = btc_c[i - F["ma_slow"] + 1:i + 1]
        if None in win:
            i += 1; continue
        f_fast = sum(win[-F["ma_fast"]:]) / F["ma_fast"]; f_slow = sum(win) / F["ma_slow"]
        if f_fast <= f_slow:
            i += 1; continue
        # ---- base: longest L in [base_min, base_max] with range <= base_range_pct of its high, and a close above it
        base = None
        for L in range(base_max, base_min - 1, -1):
            H = max(h[i - L:i]); Lo = min(l[i - L:i])
            if (H - Lo) / H <= S["base_range_pct"] / 100 and c[i] > H:
                base = (L, H, Lo); break
        if base is None:
            i += 1; continue
        L, H, Lo = base
        if i - L <= last_base_start:              # same consolidation as the last trade
            i += 1; continue
        # ---- prior move: lowest low 20–60 bars before the signal, >= prior_move_pct below the close
        pm_low = min(l[i - S["prior_move_bars_max"]:i - S["prior_move_bars_min"] + 1])
        if c[i] < pm_low * (1 + S["prior_move_pct"] / 100):
            i += 1; continue
        # ---- close in the upper half of the breakout bar
        if h[i] == l[i] or (c[i] - l[i]) / (h[i] - l[i]) < 0.5:
            i += 1; continue
        # ---- stop and ADR cap
        adr = sum((h[k] - l[k]) / c[k] for k in range(i - ST["adr_bars"], i)) / ST["adr_bars"]
        entry = o[i + 1] * (1 + slip)
        stop = l[i]
        if entry <= stop or (entry - stop) / entry > ST["adr_cap"] * adr:
            trades.append(dict(t=bars[i]["t"], status="REJECT_ADR", entry=entry, stop=stop, adr=adr,
                               stop_pct=(entry - stop) / entry))
            i += 1; continue
        R = entry - stop

        def leg(px: float, fee_out: float) -> float:   # R for one full unit exited at px
            return (px - entry) / R - fee_out * px / R - taker * entry / R

        # ---- manage
        halves = 2; partial_bar = None; exit_bar = None; reason = None
        cur_stop = stop; pnl_r = 0.0
        j = i + 1
        while j < n:
            held = j - (i + 1)
            if l[j] <= cur_stop:                       # stop first, intrabar
                pnl_r += halves * 0.5 * leg(cur_stop * (1 - slip), taker)
                exit_bar, reason = j, ("STOP" if cur_stop == stop else "STOP_BE"); break
            if halves == 2:
                tgt = entry + X["partial_r"] * R
                if h[j] >= tgt:
                    pnl_r += 0.5 * leg(tgt, maker)
                    halves = 1; partial_bar = j; cur_stop = entry
                elif held >= X["partial_bars"] and c[j] > entry:
                    pnl_r += 0.5 * leg(c[j] * (1 - slip), taker)
                    halves = 1; partial_bar = j; cur_stop = entry
            tm = sma(c, trail_ma, j)
            if tm is not None and c[j] < tm and (halves == 1 or held >= X["partial_bars"]):
                pnl_r += halves * 0.5 * leg(c[j] * (1 - slip), taker)
                exit_bar, reason = j, "TRAIL"; break
            j += 1
        if exit_bar is None:                           # still open at dataset end
            exit_bar = n - 1
            pnl_r += halves * 0.5 * leg(c[exit_bar], taker); reason = "OPEN"
        # ---- funding (rate × notional/R), half-weighted after the partial
        t_in = bars[i + 1]["t"]
        f_all = funding_between(fund, fts, t_in, bars[exit_bar]["t"] + DAY)
        if partial_bar is not None:
            f1 = funding_between(fund, fts, t_in, bars[partial_bar]["t"] + DAY)
            fund_r = (0.5 * f1 + 0.5 * f_all) * entry / R
        else:
            fund_r = f_all * entry / R
        trades.append(dict(t=bars[i]["t"], date=dt.datetime.fromtimestamp(bars[i]["t"] / 1000, dt.timezone.utc).date().isoformat(),
                           status="TRADE", entry=entry, stop=stop, stop_pct=R / entry, base_len=L, base_high=H,
                           partial_bar=(partial_bar - i) if partial_bar is not None else None,
                           bars_held=exit_bar - i, reason=reason, gross_r=pnl_r, fund_r=fund_r,
                           net_r=pnl_r - fund_r, adr=adr))
        last_base_start = i - L
        i = exit_bar + 1
    return trades


# ------------------------------------------------------------ report ----
def stats(tr: list[dict]) -> dict:
    t = [x for x in tr if x["status"] == "TRADE"]
    if not t:
        return dict(n=0, rejects=sum(1 for x in tr if x["status"] == "REJECT_ADR"))
    r = [x["net_r"] for x in t]
    m = statistics.mean(r); sd = statistics.pstdev(r) if len(r) > 1 else 0.0
    eq, peak, dd = 0.0, 0.0, 0.0
    for v in r:
        eq += v; peak = max(peak, eq); dd = min(dd, eq - peak)
    return dict(n=len(t), sum_r=sum(r), mean_r=m, t=(m / (sd / math.sqrt(len(r)))) if sd else float("nan"),
                win=sum(1 for v in r if v > 0) / len(r), gross_r=statistics.mean(x["gross_r"] for x in t),
                fund_r=statistics.mean(x["fund_r"] for x in t), med_hold=statistics.median(x["bars_held"] for x in t),
                max_r=max(r), max_dd=dd, rejects=sum(1 for x in tr if x["status"] == "REJECT_ADR"),
                trail=sum(1 for x in t if x["reason"] == "TRAIL"), stop=sum(1 for x in t if x["reason"].startswith("STOP")))


def fmt(s: dict) -> str:
    if s.get("n", 0) == 0:
        return f"n=0  rej={s.get('rejects', 0)}"
    return (f"n={s['n']:<3} ΣR={s['sum_r']:+6.1f}  R/trade={s['mean_r']:+.3f}  t={s['t']:+.2f}  win={s['win']:.0%}  "
            f"gross={s['gross_r']:+.3f} fund={s['fund_r']:.3f}  hold={s['med_hold']:.0f}d  maxR={s['max_r']:+.1f}  "
            f"DD={s['max_dd']:+.1f}  rej={s['rejects']} trail/stop={s['trail']}/{s['stop']}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--trail", type=int, default=None, help="declared secondary: trail SMA length")
    ap.add_argument("--base", type=int, nargs=2, default=None, help="declared secondary: base_min base_max")
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--start", default="2020-01")
    ap.add_argument("--split", default="2024-01-01", help="in-sample ends before this date")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    P = load_params()
    trail = a.trail or P["exit"]["trail_ma"]
    bmin, bmax = a.base or (P["setup"]["base_bars_min"], P["setup"]["base_bars_max"])
    taker, maker, slip = 0.000397, 0.0, 0.0002
    syms = a.symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    y, m = (int(x) for x in a.start.split("-"))
    split_ms = int(dt.datetime.fromisoformat(a.split).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    print(f"TS04 — trail SMA{trail}, base {bmin}–{bmax}, ADR cap {P['stop']['adr_cap']}, "
          f"filter BTC SMA{P['filter']['ma_fast']}/{P['filter']['ma_slow']}, taker {taker:.4%} slip {slip:.2%}, "
          f"funding real. Data USDT perps {a.start}→, IS/OOS split {a.split}")
    btc = history("BTCUSDT", (y, m), "1d", verbose=False)
    all_tr = []
    for s in syms:
        bars = history(s, (y, m), "1d", verbose=False)
        fund = funding_history(s, (y, m))
        tr = run(bars, btc, fund, P, trail, bmin, bmax, taker, maker, slip)
        for x in tr:
            x["symbol"] = s
        all_tr += tr
        print(f"{s:<8} {fmt(stats(tr))}")
        print(f"         B&H {bars[0]['c']:,.0f}→{bars[-1]['c']:,.0f} = {bars[-1]['c'] / bars[0]['c'] - 1:+.0%} · {len(bars)} bars · {len(fund)} funding prints")
    print(f"{'ALL':<8} {fmt(stats(all_tr))}")
    ins = [x for x in all_tr if x['t'] < split_ms]; oos = [x for x in all_tr if x['t'] >= split_ms]
    print(f"{'IS':<8} {fmt(stats(ins))}")
    print(f"{'OOS':<8} {fmt(stats(oos))}")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        with open(a.out, "w") as f:
            json.dump(dict(version=__version__, params=P, trail=trail, base=[bmin, bmax], trades=all_tr), f, indent=1, default=str)
    return all_tr


if __name__ == "__main__":
    main()
