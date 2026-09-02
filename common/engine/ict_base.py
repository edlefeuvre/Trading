r"""common.engine.ict_base — the locked ICT base engine (sweep → CHoCH → FVG, pool exit).

Moved VERBATIM from the `ENGINE (verbatim)` blocks of choch_watch.py and choch_sizes.py
on 2 Sep 2026. Behaviour is identical for the default arguments; the only change is
that the encoding choices are now named parameters with those defaults, so a strategy's
params.yaml can state them and `check-strategy` can see them.

    pivots(bars, k)                       fractal pivots, strict unique extreme over 2k+1
    setups(bars, k)                       CHoCH events (close beyond the last lower-high / higher-low)
    live_state(bars, ...)                 the watcher's view: placed / resting / open / closed / expired
    build_trades(bars, ...)               the backtest's view: one dict per completed trade, net R

Bars are dicts with keys t (ms), o, h, l, c (floats). Any change here is a MAJOR change
to every strategy that imports it — the pre-commit hook enforces the change-log row.
"""
from __future__ import annotations

# Encoding choices — defaults are the locked spec of 30 Aug 2026
K = 5                 # pivot width
LIVE_BARS = 32        # limit-order lifetime, anchored to the FVG bar
SWEEP_RECLAIM = 4     # close back through the swept level within this many bars of the sweep bar
FVG_WINDOW = 2        # FVG must print on the CHoCH bar or within this many bars after
TAKER_FEE = 0.0004    # charged on stop-outs only (maker entry/target free); funding not modelled


def pivots(bars, k=K):
    ph, pl = [], []
    for p in range(k, len(bars) - k):
        wh = [bars[j]["h"] for j in range(p - k, p + k + 1)]
        wl = [bars[j]["l"] for j in range(p - k, p + k + 1)]
        if bars[p]["h"] == max(wh) and wh.count(bars[p]["h"]) == 1:
            ph.append((p, bars[p]["h"], p + k))
        if bars[p]["l"] == min(wl) and wl.count(bars[p]["l"]) == 1:
            pl.append((p, bars[p]["l"], p + k))
    return ph, pl


def setups(bars, k=K):
    ph, pl = pivots(bars, k)
    ch, cl = [], []
    hi = lo = 0
    ab = abr = None
    out = []
    for i in range(len(bars)):
        while hi < len(ph) and ph[hi][2] <= i:
            ch.append(ph[hi][:2]); hi += 1
            ab = (ch[-2], ch[-1]) if len(ch) >= 2 and ch[-1][1] < ch[-2][1] else None
        while lo < len(pl) and pl[lo][2] <= i:
            cl.append(pl[lo][:2]); lo += 1
            abr = (cl[-2], cl[-1]) if len(cl) >= 2 and cl[-1][1] > cl[-2][1] else None
        c = bars[i]["c"]
        if ab and c > ab[1][1]:
            out.append(dict(i=i, d=1, A=ab[0], B=ab[1], lows=list(cl), highs=list(ch))); ab = None
        if abr and c < abr[1][1]:
            out.append(dict(i=i, d=-1, A=abr[0], B=abr[1], lows=list(cl), highs=list(ch))); abr = None
    return out


def _sweep_and_fvg(bars, ev, n, sweep_reclaim, fvg_window):
    """Shared by live_state and build_trades. Returns (b, L, j, mid, disc, risk, T1) or None."""
    i, d = ev["i"], ev["d"]
    Bp = ev["B"][0]
    if d == 1:
        b = min(range(Bp, i + 1), key=lambda x: bars[x]["l"]); L = bars[b]["l"]
        olds = [p for p in ev["lows"] if p[0] < b]
        if not olds:
            return None
        ref = olds[-1][1]
        swept = L < ref and any(bars[m]["c"] > ref for m in range(b, min(b + sweep_reclaim, i + 1)))
    else:
        b = max(range(Bp, i + 1), key=lambda x: bars[x]["h"]); L = bars[b]["h"]
        olds = [p for p in ev["highs"] if p[0] < b]
        if not olds:
            return None
        ref = olds[-1][1]
        swept = L > ref and any(bars[m]["c"] < ref for m in range(b, min(b + sweep_reclaim, i + 1)))
    if not swept:
        return None
    fvg = None
    for j in range(max(i, 2), min(i + fvg_window + 1, n)):
        if d == 1 and bars[j]["l"] > bars[j - 2]["h"]:
            fvg = (j, (bars[j - 2]["h"] + bars[j]["l"]) / 2); break
        if d == -1 and bars[j]["h"] < bars[j - 2]["l"]:
            fvg = (j, (bars[j]["h"] + bars[j - 2]["l"]) / 2); break
    if not fvg:
        return None
    j, mid = fvg
    H = (max(bars[x]["h"] for x in range(b, j + 1)) if d == 1 else min(bars[x]["l"] for x in range(b, j + 1)))
    eq = (L + H) / 2
    disc = (mid <= eq) if d == 1 else (mid >= eq)
    risk = (mid - L) * d
    if risk <= 0:
        return None
    T1 = ev["A"][1]
    if (T1 - mid) * d <= 0:
        return None
    return b, L, j, mid, disc, risk, T1


def live_state(bars, k=K, live_bars=LIVE_BARS, report_all=False, sweep_reclaim=SWEEP_RECLAIM,
               fvg_window=FVG_WINDOW, discount_only=True):
    """The watcher's view of every setup in `bars`. Verbatim logic of choch_watch.live_state."""
    n = len(bars)
    busy_until = -1
    events = []
    for ev in setups(bars, k):
        i, d = ev["i"], ev["d"]
        if i <= busy_until:
            continue
        r = _sweep_and_fvg(bars, ev, n, sweep_reclaim, fvg_window)
        if r is None:
            continue
        b, L, j, mid, disc, risk, T1 = r
        if discount_only and not disc:
            continue                                   # discount-only — locked

        tk = dict(d=d, mid=mid, stop=L, target=T1, risk=risk,
                  stop_pct=100 * risk / mid, poolR=(T1 - mid) * d / risk,
                  fvg_bar=j, t_placed=bars[j]["t"], choch_bar=i, sweep_bar=b)

        fill = None
        for m in range(j + 1, min(j + live_bars + 1, n)):
            if (d == 1 and bars[m]["l"] <= mid) or (d == -1 and bars[m]["h"] >= mid):
                fill = m; break

        if fill is None:
            if j + live_bars >= n - 1:
                tk["status"] = "placed" if j == n - 1 else "resting"
                tk["bars_left"] = j + live_bars - (n - 1)
                events.append(tk)
            elif report_all:
                tk["status"] = "expired"
                tk["t_expired"] = bars[min(j + live_bars, n - 1)]["t"]
                events.append(tk)
            continue

        exit_bar = None
        bb = bars[fill]
        if (d == 1 and bb["l"] <= L) or (d == -1 and bb["h"] >= L):
            exit_bar = fill
        else:
            for m in range(fill + 1, n):
                bb = bars[m]
                if (d == 1 and bb["l"] <= L) or (d == -1 and bb["h"] >= L):
                    exit_bar = m; break
                if (d == 1 and bb["h"] >= T1) or (d == -1 and bb["l"] <= T1):
                    exit_bar = m; break

        if exit_bar is None:
            tk["status"] = "open"
            tk["t_filled"] = bars[fill]["t"]
            tk["unreal_R"] = (bars[n - 1]["c"] - mid) * d / risk
            events.append(tk)
            busy_until = n
        else:
            if report_all:
                hit_stop = (d == 1 and bars[exit_bar]["l"] <= L) or (d == -1 and bars[exit_bar]["h"] >= L)
                tk["status"] = "closed"
                tk["t_filled"] = bars[fill]["t"]
                tk["t_exit"] = bars[exit_bar]["t"]
                tk["outcome"] = "stop" if hit_stop else "target"
                tk["net_R"] = (-1.0 - TAKER_FEE * L / risk) if hit_stop else tk["poolR"]
                events.append(tk)
            busy_until = fill
    return events


def build_trades(bars, k=K, live_bars=LIVE_BARS, sweep_reclaim=SWEEP_RECLAIM, fvg_window=FVG_WINDOW,
                 taker_fee=TAKER_FEE):
    """The backtest's view. Verbatim logic of choch_sizes.build_trades: every completed trade,
    with `disc` recorded (the caller filters on it) and net R after the stop-out fee."""
    trades = []
    busy_until = -1
    n = len(bars)
    for ev in setups(bars, k):
        i, d = ev["i"], ev["d"]
        if i <= busy_until:
            continue
        r = _sweep_and_fvg(bars, ev, n, sweep_reclaim, fvg_window)
        if r is None:
            continue
        b, L, j, mid, disc, risk, T1 = r
        fill = None
        for m in range(j + 1, min(j + live_bars + 1, n)):
            if (d == 1 and bars[m]["l"] <= mid) or (d == -1 and bars[m]["h"] >= mid):
                fill = m; break
        if fill is None:
            continue
        res = None
        bb = bars[fill]
        if (d == 1 and bb["l"] <= L) or (d == -1 and bb["h"] >= L):
            res = (-1.0, "s")
        else:
            for m in range(fill + 1, n):
                bb = bars[m]
                if (d == 1 and bb["l"] <= L) or (d == -1 and bb["h"] >= L):
                    res = (-1.0, "s"); break
                if (d == 1 and bb["h"] >= T1) or (d == -1 and bb["l"] <= T1):
                    res = ((T1 - mid) * d / risk, "t"); break
        if res is None:
            continue
        g, kind = res
        busy_until = fill
        fee = (taker_fee * L / risk) if kind == "s" else 0.0
        trades.append(dict(t=bars[fill]["t"], disc=disc, net=g - fee, d=d, kind=kind))
    return trades
