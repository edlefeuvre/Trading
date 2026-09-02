"""Engine equivalence: common.engine.ict_base must reproduce the pre-migration watcher and
sizing script exactly, on random and on structured synthetic bars. If this fails, the
migration changed the strategy."""
import random

from common.engine import ict_base as new

# ORACLE: verbatim copies of the pre-migration functions (choch_watch.py / choch_sizes.py, 31 Aug 2026)
K = 5
LIVE_BARS = 32

def pivots(bars, k):
    ph, pl = [], []
    for p in range(k, len(bars)-k):
        wh = [bars[j]["h"] for j in range(p-k, p+k+1)]
        wl = [bars[j]["l"] for j in range(p-k, p+k+1)]
        if bars[p]["h"] == max(wh) and wh.count(bars[p]["h"]) == 1: ph.append((p, bars[p]["h"], p+k))
        if bars[p]["l"] == min(wl) and wl.count(bars[p]["l"]) == 1: pl.append((p, bars[p]["l"], p+k))
    return ph, pl

def setups(bars, k):
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

def live_state(bars, k=K, live_bars=LIVE_BARS, report_all=False):
    n = len(bars)
    busy_until = -1
    events = []
    for ev in setups(bars, k):
        i, d = ev["i"], ev["d"]
        if i <= busy_until: continue
        Bp = ev["B"][0]
        if d == 1:
            b = min(range(Bp, i+1), key=lambda x: bars[x]["l"]); L = bars[b]["l"]
            olds = [p for p in ev["lows"] if p[0] < b]
            if not olds: continue
            ref = olds[-1][1]
            swept = L < ref and any(bars[m]["c"] > ref for m in range(b, min(b+4, i+1)))
        else:
            b = max(range(Bp, i+1), key=lambda x: bars[x]["h"]); L = bars[b]["h"]
            olds = [p for p in ev["highs"] if p[0] < b]
            if not olds: continue
            ref = olds[-1][1]
            swept = L > ref and any(bars[m]["c"] < ref for m in range(b, min(b+4, i+1)))
        if not swept: continue
        fvg = None
        for j in range(max(i, 2), min(i+3, n)):
            if d == 1 and bars[j]["l"] > bars[j-2]["h"]: fvg = (j, (bars[j-2]["h"]+bars[j]["l"])/2); break
            if d == -1 and bars[j]["h"] < bars[j-2]["l"]: fvg = (j, (bars[j]["h"]+bars[j-2]["l"])/2); break
        if not fvg: continue
        j, mid = fvg
        H = (max(bars[x]["h"] for x in range(b, j+1)) if d == 1 else min(bars[x]["l"] for x in range(b, j+1)))
        eq = (L+H)/2
        disc = (mid <= eq) if d == 1 else (mid >= eq)
        if not disc: continue                      # discount-only — locked
        risk = (mid - L)*d
        if risk <= 0: continue
        T1 = ev["A"][1]
        if (T1 - mid)*d <= 0: continue

        tk = dict(d=d, mid=mid, stop=L, target=T1, risk=risk,
                  stop_pct=100*risk/mid, poolR=(T1-mid)*d/risk,
                  fvg_bar=j, t_placed=bars[j]["t"])

        fill = None
        for m in range(j+1, min(j+live_bars+1, n)):
            if (d == 1 and bars[m]["l"] <= mid) or (d == -1 and bars[m]["h"] >= mid):
                fill = m; break

        if fill is None:
            if j + live_bars >= n - 1:
                tk["status"] = "placed" if j == n-1 else "resting"
                tk["bars_left"] = j + live_bars - (n-1)
                events.append(tk)
            elif report_all:
                tk["status"] = "expired"
                events.append(tk)
            continue

        exit_bar = None
        bb = bars[fill]
        if (d == 1 and bb["l"] <= L) or (d == -1 and bb["h"] >= L):
            exit_bar = fill
        else:
            for m in range(fill+1, n):
                bb = bars[m]
                if (d == 1 and bb["l"] <= L) or (d == -1 and bb["h"] >= L): exit_bar = m; break
                if (d == 1 and bb["h"] >= T1) or (d == -1 and bb["l"] <= T1): exit_bar = m; break

        if exit_bar is None:
            tk["status"] = "open"
            tk["t_filled"] = bars[fill]["t"]
            tk["unreal_R"] = (bars[n-1]["c"] - mid)*d/risk
            events.append(tk)
            busy_until = n
        else:
            if report_all:
                hit_stop = (d == 1 and bars[exit_bar]["l"] <= L) or (d == -1 and bars[exit_bar]["h"] >= L)
                tk["status"] = "closed"
                tk["t_filled"] = bars[fill]["t"]
                tk["outcome"] = "stop" if hit_stop else "target"
                events.append(tk)
            busy_until = fill
    return events

def build_trades(bars, k):
    trades = []
    busy_until = -1
    n = len(bars)
    for ev in setups(bars, k):
        i, d = ev["i"], ev["d"]
        if i <= busy_until: continue
        Bp = ev["B"][0]
        if d == 1:
            b = min(range(Bp, i+1), key=lambda x: bars[x]["l"]); L = bars[b]["l"]
            olds = [p for p in ev["lows"] if p[0] < b]
            if not olds: continue
            ref = olds[-1][1]
            swept = L < ref and any(bars[m]["c"] > ref for m in range(b, min(b+4, i+1)))
        else:
            b = max(range(Bp, i+1), key=lambda x: bars[x]["h"]); L = bars[b]["h"]
            olds = [p for p in ev["highs"] if p[0] < b]
            if not olds: continue
            ref = olds[-1][1]
            swept = L > ref and any(bars[m]["c"] < ref for m in range(b, min(b+4, i+1)))
        if not swept: continue
        fvg = None
        for j in range(max(i, 2), min(i+3, n)):
            if d == 1 and bars[j]["l"] > bars[j-2]["h"]: fvg = (j, (bars[j-2]["h"]+bars[j]["l"])/2); break
            if d == -1 and bars[j]["h"] < bars[j-2]["l"]: fvg = (j, (bars[j]["h"]+bars[j-2]["l"])/2); break
        if not fvg: continue
        j, mid = fvg
        H = (max(bars[x]["h"] for x in range(b, j+1)) if d == 1 else min(bars[x]["l"] for x in range(b, j+1)))
        eq = (L+H)/2
        disc = (mid <= eq) if d == 1 else (mid >= eq)
        risk = (mid - L)*d
        if risk <= 0: continue
        T1 = ev["A"][1]
        if (T1 - mid)*d <= 0: continue
        fill = None
        for m in range(j+1, min(j+33, n)):
            if (d == 1 and bars[m]["l"] <= mid) or (d == -1 and bars[m]["h"] >= mid):
                fill = m; break
        if fill is None: continue
        r = None
        bb = bars[fill]
        if (d == 1 and bb["l"] <= L) or (d == -1 and bb["h"] >= L):
            r = (-1.0, "s")
        else:
            for m in range(fill+1, n):
                bb = bars[m]
                if (d == 1 and bb["l"] <= L) or (d == -1 and bb["h"] >= L): r = (-1.0, "s"); break
                if (d == 1 and bb["h"] >= T1) or (d == -1 and bb["l"] <= T1): r = ((T1-mid)*d/risk, "t"); break
        if r is None: continue
        g, kind = r
        busy_until = fill
        fee = (0.0004 * L / risk) if kind == "s" else 0.0
        trades.append(dict(t=bars[fill]["t"], disc=disc, net=g - fee))
    return trades



def synth(seed, n=1200):
    rnd = random.Random(seed)
    bars, p = [], 100.0
    for i in range(n):
        drift = rnd.choice([-1, 1]) * rnd.random() * 0.6
        o = p; c = max(1.0, p + drift)
        h = max(o, c) + rnd.random() * 0.4
        l = min(o, c) - rnd.random() * 0.4
        bars.append(dict(t=1_700_000_000_000 + i * 900_000, o=o, h=h, l=l, c=c, v=1.0))
        p = c
    return bars


def _strip(evs):
    keys = ("d", "mid", "stop", "target", "risk", "stop_pct", "poolR", "fvg_bar", "t_placed", "status",
            "bars_left", "t_filled", "unreal_R", "outcome")
    return [{k: e[k] for k in keys if k in e} for e in evs]


def test_pivots_and_setups_identical():
    for seed in range(20):
        bars = synth(seed)
        assert new.pivots(bars, 5) == pivots(bars, 5)
        assert new.setups(bars, 5) == setups(bars, 5)


def test_live_state_identical():
    for seed in range(40):
        bars = synth(seed)
        for report_all in (False, True):
            assert _strip(new.live_state(bars, report_all=report_all)) == _strip(live_state(bars, report_all=report_all)), seed


def test_build_trades_identical():
    for seed in range(40):
        bars = synth(seed)
        a = [(t["t"], t["disc"], round(t["net"], 12)) for t in new.build_trades(bars)]
        b = [(t["t"], t["disc"], round(t["net"], 12)) for t in build_trades(bars, 5)]
        assert a == b, seed


def test_engine_produces_setups_on_synthetic_data():
    total = sum(len(new.live_state(synth(s), report_all=True)) for s in range(40))
    assert total > 0, "synthetic series never produced a setup — test is not exercising the engine"
