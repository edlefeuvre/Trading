r"""Trading Book — daily report (07:00 local, Digest topic).

Book-level, not per strategy. Reads the exchange with SERVER_RO (wallet, positions, open
orders, last-24h realised P&L / commission / funding), attributes every position and order to
the strategy whose announced ticket it matches (symbol, side, price within tolerance, announced
within `attribute_days`), and lists whatever matches nothing as OUTSIDE STRATEGIES — the
discretionary trades the charter says must be visible. Then one block per strategy (paper
activity and runner health from its cycle log), then the book's standing.

    python -m common.reports.daily            # send to config/book.yaml alerts.daily_to
    python -m common.reports.daily --stdout   # print
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from common.alerts import telegram

__version__ = "1.10"
REPO = Path(__file__).resolve().parent.parent.parent
TZ = dt.timezone.utc
W = 32


def load_yaml(path: Path):
    try:
        import yaml  # type: ignore
    except ImportError:
        sys.exit("pyyaml is required:  python -m pip install pyyaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def rule(title: str) -> str:
    t = f"── {title} "
    return t + "─" * max(0, W - len(t))


def fnum(x: float, dp: int = 2) -> str:
    return f"{x:+,.{dp}f}" if x else f"{0:.{dp}f}"


def strategies() -> list[dict]:
    out = []
    for d in sorted((REPO / "strategies").glob("TS*")):
        if not (d / "STRATEGY.md").is_file():
            continue
        params = load_yaml(d / "config" / "params.yaml") if (d / "config" / "params.yaml").is_file() else {}
        uni = load_yaml(d / "config" / "universe.yaml") if (d / "config" / "universe.yaml").is_file() else {}
        tiers = {str(r["symbol"]).upper(): float(r.get("tier", 0) or 0) for r in uni.get("symbols", []) if isinstance(r, dict)}
        st = {}
        sp = d / "results" / "state.json"
        if sp.is_file():
            try:
                st = json.load(open(sp, encoding="utf-8"))
            except Exception:  # noqa: BLE001
                st = {}
        out.append(dict(id=d.name.split("_")[0], slug=d.name, dir=d, params=params, tiers=tiers, state=st,
                        mode=str(params.get("mode", "PAPER")).upper()))
    return out


def announced_setups(strats: list[dict], days: int) -> list[dict]:
    """Setups announced within `days`. Keys are 'SYM:t_placed' (value = ticket dict for setups
    announced since v1.10, True before that — those can only be matched by symbol and time)."""
    since = (dt.datetime.now(TZ) - dt.timedelta(days=days)).timestamp() * 1000
    out = []
    for s in strats:
        for k, v in s["state"].items():
            parts = k.split(":")
            if len(parts) != 2 or not parts[1].isdigit():
                continue                       # fill/closed/expiring keys and bookkeeping entries
            t = int(parts[1])
            if t < since:
                continue
            if isinstance(v, dict):
                out.append({**v, "ts": s["id"], "weak": False})
            else:
                out.append({"sym": parts[0], "t": t, "ts": s["id"], "weak": True})
    return out


def attribute(sym: str, side: str | None, price: float | None, setups: list[dict], tol_pct: float) -> str | None:
    """Strategy id whose announced ticket this exchange item matches, else None.
    Strong: side+price within tolerance of entry (same side) or stop/target (opposite side).
    Weak (setup announced before tickets were recorded, or price unknown): symbol + window → 'TS01*'."""
    weak_hit = None
    for su in setups:
        if su["sym"] != sym:
            continue
        if su.get("weak") or side is None or price is None or not su.get("entry"):
            weak_hit = weak_hit or su["ts"] + "*"
            continue
        cands = [su["entry"]] if side == su["side"] else [su.get("stop"), su.get("target")]
        for ref in cands:
            if ref and abs(price - ref) / ref * 100 <= tol_pct:
                return su["ts"]
    return weak_hit


def exchange_block(book: dict, strats: list[dict]) -> tuple[list[str], list[str], dict | None]:
    """Returns (lines, outside_lines, data)."""
    rep = book.get("report", {})
    hours = int(rep.get("hours", 24)); days = int(rep.get("attribute_days", 4)); tol = float(rep.get("price_tolerance_pct", 0.15))
    key = "SERVER_RO"
    try:
        from common.exchange import binance
        if key not in binance.list_keys():
            return [rule(f"Binance · {key}"), "not configured"], [], None
        c = binance.Client(key); c.sync_time()
        bal = {b["asset"]: b for b in c._request(binance.FAPI, "GET", "/fapi/v2/balance", signed=True)}
        pos = c.positions(); oo = c.open_orders(); inc = c.income(hours)
    except Exception as e:  # noqa: BLE001
        return [rule("Binance"), f"read failed: {str(e)[:60]}"], [], {"error": str(e)[:200]}

    setups = announced_setups(strats, days)
    data = {"hours": hours, "wallet": {}, "positions": [], "orders": [], "by_symbol": []}
    lines = [rule(f"Binance · {key}")]
    for asset in ("USDC", "USDT"):
        b = bal.get(asset)
        if b and (float(b["balance"]) or float(b["crossUnPnl"])):
            lines.append(f"{asset} wallet {float(b['balance']):>9,.2f} avail {float(b['availableBalance']):>8,.2f}")
            data["wallet"][asset] = {"balance": float(b["balance"]), "avail": float(b["availableBalance"])}
    upnl = sum(float(p["unRealizedProfit"]) for p in pos)
    lines.append(f"unrealised {fnum(upnl):>8}  positions {len(pos)}  orders {len(oo)}")

    outside: list[str] = []
    lines.append("Positions" if pos else "Positions none")
    for p in pos:
        qty, entry, mark = float(p["positionAmt"]), float(p["entryPrice"]), float(p["markPrice"])
        side = "LONG " if qty > 0 else "SHORT"
        tag = attribute(p["symbol"], "BUY" if qty > 0 else "SELL", entry, setups, tol) or "—"
        row = [f" {p['symbol']:<9}{side} {abs(qty):>8g} @{entry:g}", f"   [{tag}] mark {mark:g} uPnL {fnum(float(p['unRealizedProfit']))}"]
        lines += row
        data["positions"].append(dict(symbol=p["symbol"], side=side.strip(), qty=abs(qty), entry=entry, mark=mark,
                                      upnl=float(p["unRealizedProfit"]), tag=tag))
        if tag == "—":
            outside.append(dict(kind="position", symbol=p["symbol"], detail=f"{side.strip()} {abs(qty):g} @ {entry:g} · uPnL {fnum(float(p['unRealizedProfit']))}", tag="—"))
    lines.append("Open orders" if oo else "Open orders none")
    for o in oo[:10]:
        kind = {"LIMIT": "LIM", "STOP_MARKET": "SL ", "STOP": "SL ", "TAKE_PROFIT": "TP ", "TAKE_PROFIT_MARKET": "TP "}.get(o["type"], o["type"][:3])
        price = float(o["price"]) or float(o.get("stopPrice", 0))
        tag = attribute(o["symbol"], o["side"], price, setups, tol) or "—"
        row = f" {o['symbol']:<9}{o['side']:<4} {kind} {float(o['origQty']):>7g} @{price:g} [{tag}]"
        lines.append(row)
        data["orders"].append(dict(symbol=o["symbol"], side=o["side"], type=kind.strip(), qty=float(o["origQty"]), price=price, tag=tag))
        if tag == "—":
            outside.append(dict(kind="order", symbol=o["symbol"], detail=f"{o['side']} {kind.strip()} {float(o['origQty']):g} @ {price:g}", tag="—"))
    if len(oo) > 10:
        lines.append(f" … {len(oo) - 10} more")

    by, by_sym = {}, {}
    for r in inc:
        by[r["incomeType"]] = by.get(r["incomeType"], 0.0) + float(r["income"])
        if r["incomeType"] == "REALIZED_PNL" and r.get("symbol"):
            by_sym[r["symbol"]] = by_sym.get(r["symbol"], 0.0) + float(r["income"])
    realised, fees, funding = by.get("REALIZED_PNL", 0.0), by.get("COMMISSION", 0.0), by.get("FUNDING_FEE", 0.0)
    lines.append(f"{hours}h realised {fnum(realised):>8} fees {fnum(fees):>7}")
    lines.append(f"    funding  {fnum(funding):>8} net  {fnum(realised + fees + funding):>7}")
    for sym, v in sorted(by_sym.items(), key=lambda kv: -abs(kv[1])):
        tag = attribute(sym, None, None, setups, tol)
        lines.append(f"    {sym:<10}{fnum(v):>9}  [{tag or '—'}]")
        data["by_symbol"].append((sym, v, tag))
        if not tag:
            outside.append(dict(kind="realised", symbol=sym, detail=f"{fnum(v)} in the last {hours}h", tag="—"))
    data.update(upnl=upnl, realised=realised, fees=fees, funding=funding, net24=realised + fees + funding,
                n_pos=len(pos), n_orders=len(oo))
    return lines, outside, data


def strategy_block(s: dict, hours: int) -> list[str]:
    log = s["dir"] / "logs" / f"{s['id']}-runner.jsonl"
    since = dt.datetime.now(TZ) - dt.timedelta(hours=hours)
    cycles, sent, last = 0, [], None
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if r.get("event") != "cycle":
                continue
            ts = dt.datetime.fromisoformat(r["ts"])
            if ts < since:
                continue
            cycles += 1; last = ts; sent += r.get("sent", [])
    c = {k: sum(1 for x in sent if x.startswith(k)) for k in ("SETUP", "FILLED", "STOPPED", "TARGET", "EXPIRED")}
    funded = sum(1 for t in s["tiers"].values() if t > 0)
    last_s = last.strftime("%H:%M") if last else "—"
    s["_stats"] = {**c, "cycles": cycles, "expected": hours * 4, "last": last_s}
    return [rule(f"{s['id']} · {s['mode']} · {funded} funded"),
            f"setups {c['SETUP']} · filled {c['FILLED']} · stop {c['STOPPED']} · tgt {c['TARGET']} · exp {c['EXPIRED']}",
            f"runner {cycles}/{hours * 4} cycles · last {last_s} UTC"]


def book_block(book: dict, strats: list[dict]) -> list[str]:
    b = float(book.get("book_usd", 0) or 0)
    cap = max(b * 0.01, float(book.get("unit_floor_usd", 20)))
    modes = ", ".join(f"{s['id']} {s['mode']}" for s in strats) or "no strategies"
    return [rule("Book"),
            f"book ${b:,.0f} → ceiling ${cap:,.0f}/trade",
            f"caps: {book.get('max_open_positions', '?')} pos · ${float(book.get('max_notional_usd', 0)):,.0f} · -{book.get('daily_loss_stop_r', '?')}R/day",
            modes]


# ------------------------------------------------------------- HTML statement ---
CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:14px;background:#f3f4f6;color:#111}
.wrap{max-width:640px;margin:0 auto;background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:18px 20px 26px}
h1{font-size:18px;margin:0 0 2px}h2{font-size:14px;margin:18px 0 6px;color:#444;text-transform:uppercase;letter-spacing:.04em}
.sub{color:#666;font-size:13px}table{border-collapse:collapse;width:100%;font-size:14px;background:#fff}
th,td{padding:6px 8px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap}th{color:#666;font-weight:600;font-size:12px}
table{width:auto;min-width:60%}.tag.weak{background:#eef;color:#335;border:1px dashed #99a}.legend{font-size:12px;color:#666;margin-top:6px}
td:first-child,th:first-child{text-align:left}.pos{color:#0a7d3b}.neg{color:#b42318}.tag{font-size:11px;padding:1px 6px;border-radius:9px;background:#eef;color:#335}
.out{background:#fff4e5;color:#8a4b00}.kpi{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0}.kpi div{background:#fff;border:1px solid #eee;border-radius:8px;padding:8px 10px;min-width:120px}
.kpi b{display:block;font-size:16px}.kpi span{font-size:11px;color:#666}
"""


def _cls(x: float) -> str:
    return "pos" if x > 0 else "neg" if x < 0 else ""


def html_statement(stamp: str, mode: str, book: dict, strats: list[dict], ex: dict | None, outside_rows: list[str]) -> str:
    def money(x): return f'<span class="{_cls(x)}">{x:+,.2f}</span>'
    def tagcell(tag):
        if tag == "—" or not tag:
            return "<span class='tag out'>outside</span>"
        if tag.endswith("*"):
            return f"<span class='tag weak'>{tag[:-1]}</span>"
        return f"<span class='tag'>{tag}</span>"
    parts = [f"<style>{CSS}</style><div class='wrap'>", f"<h1>Trading Book · daily statement</h1><div class='sub'>{stamp}</div>"]
    if ex is None or "error" in (ex or {}):
        parts.append(f"<h2>Binance</h2><p>{'not configured' if ex is None else ex['error']}</p>")
    else:
        parts.append("<h2>Binance · SERVER_RO</h2><div class='kpi'>")
        for asset, b in ex["wallet"].items():
            parts.append(f"<div><b>{b['balance']:,.2f}</b><span>{asset} wallet · avail {b['avail']:,.2f}</span></div>")
        parts.append(f"<div><b class='{_cls(ex['upnl'])}'>{ex['upnl']:+,.2f}</b><span>unrealised</span></div>")
        parts.append(f"<div><b class='{_cls(ex['net24'])}'>{ex['net24']:+,.2f}</b><span>{ex['hours']}h net (realised {ex['realised']:+,.2f}, fees {ex['fees']:+,.2f}, funding {ex['funding']:+,.2f})</span></div></div>")
        parts.append("<h2>Positions</h2>")
        if ex["positions"]:
            parts.append("<table><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Mark</th><th>uPnL</th><th>Strategy</th></tr>")
            for p in ex["positions"]:
                parts.append(f"<tr><td>{p['symbol']}</td><td>{p['side']}</td><td>{p['qty']:g}</td><td>{p['entry']:g}</td><td>{p['mark']:g}</td><td>{money(p['upnl'])}</td><td>{tagcell(p['tag'])}</td></tr>")
            parts.append("</table>")
        else:
            parts.append("<p class='sub'>none</p>")
        parts.append("<h2>Open orders</h2>")
        if ex["orders"]:
            parts.append("<table><tr><th>Symbol</th><th>Side</th><th>Type</th><th>Qty</th><th>Price</th><th>Strategy</th></tr>")
            for o in ex["orders"]:
                parts.append(f"<tr><td>{o['symbol']}</td><td>{o['side']}</td><td>{o['type']}</td><td>{o['qty']:g}</td><td>{o['price']:g}</td><td>{tagcell(o['tag'])}</td></tr>")
            parts.append("</table>")
        else:
            parts.append("<p class='sub'>none</p>")
        if ex["by_symbol"]:
            parts.append(f"<h2>Realised · last {ex['hours']}h by symbol</h2><table><tr><th>Symbol</th><th>Realised</th><th>Strategy</th></tr>")
            for sym, v, tag in ex["by_symbol"]:
                parts.append(f"<tr><td>{sym}</td><td>{money(v)}</td><td>{tagcell(tag)}</td></tr>")
            parts.append("</table>")
        parts.append("<div class='legend'>Strategy tags: solid = matches a ticket's price and side; dashed = same symbol as a recent setup (announced before tickets were recorded, or a realised total); <span class='tag out'>outside</span> = no strategy setup.</div>")
    parts.append("<h2>Outside strategies</h2>")
    if not outside_rows:
        parts.append("<p class='sub'>none — every position, order and realised total matches a strategy setup</p>")
    else:
        parts.append("<table><tr><th>What</th><th>Symbol</th><th>Detail</th></tr>")
        for o in outside_rows:
            parts.append(f"<tr><td>{o['kind']}</td><td>{o['symbol']}</td><td>{o['detail']}</td></tr>")
        parts.append("</table>")
    for s_ in strats:
        st = s_["_stats"]
        parts.append(f"<h2>{s_['id']} · {s_['mode']}</h2><div class='kpi'>"
                     f"<div><b>{st['SETUP']}</b><span>setups</span></div><div><b>{st['FILLED']}</b><span>filled</span></div>"
                     f"<div><b>{st['STOPPED']}</b><span>stopped</span></div><div><b>{st['TARGET']}</b><span>targets</span></div>"
                     f"<div><b>{st['EXPIRED']}</b><span>expired</span></div><div><b>{st['cycles']}/{st['expected']}</b><span>runner cycles · last {st['last']}</span></div></div>"
                     f"<div class='sub'>{s_['slug']} · {sum(1 for t in s_['tiers'].values() if t > 0)} symbols funded</div>")
    b = float(book.get("book_usd", 0) or 0); cap = max(b * 0.01, float(book.get("unit_floor_usd", 20)))
    parts.append(f"<h2>Book</h2><div class='kpi'><div><b>${b:,.0f}</b><span>ring-fenced book</span></div><div><b>${cap:,.0f}</b><span>ceiling per trade</span></div>"
                 f"<div><b>{book.get('max_open_positions','?')} · ${float(book.get('max_notional_usd',0)):,.0f}</b><span>max positions · notional</span></div>"
                 f"<div><b>-{book.get('daily_loss_stop_r','?')}R</b><span>daily stop</span></div></div>")
    parts.append("</div>")
    return "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Trading Book daily</title></head><body>" + "".join(parts) + "</body></html>"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stdout", action="store_true")
    a = ap.parse_args(argv)
    book = load_yaml(REPO / "config" / "book.yaml")
    strats = strategies()
    hours = int(book.get("report", {}).get("hours", 24))
    now = dt.datetime.now(TZ)
    try:
        from zoneinfo import ZoneInfo
        loc = now.astimezone(ZoneInfo("Europe/Gibraltar"))
        stamp = f"{loc:%a %d %b} · {loc:%H:%M} Gib ({now:%H:%M} UTC)"
    except Exception:  # noqa: BLE001
        stamp = f"{now:%a %d %b %H:%M} UTC"
    mode = "DAILY"   # the statement is real exchange state; modes belong to the strategies' own lines
    ex_lines, outside, ex = exchange_block(book, strats)
    strat_lines = []
    for s_ in strats:
        strat_lines += strategy_block(s_, hours)
    outside_txt = [f" {o['kind']:<8} {o['symbol']:<9} {o['detail']}" for o in outside]
    full = ex_lines + [rule("OUTSIDE STRATEGIES")] + (outside_txt or ["none — every position and order matches a ticket"]) \
        + strat_lines + book_block(book, strats)

    # ---- short summary for the topic ----
    summ = ["<b>DAILY · TRADING BOOK</b>", stamp]
    if ex and "error" not in ex:
        w = next(iter(ex["wallet"].values()), None)
        summ.append(f"wallet {w['balance']:,.2f} · unrealised {ex['upnl']:+,.2f}" if w else f"unrealised {ex['upnl']:+,.2f}")
        summ.append(f"{ex['hours']}h net {ex['net24']:+,.2f} (realised {ex['realised']:+,.2f}, fees {ex['fees']:+,.2f}, funding {ex['funding']:+,.2f})")
        summ.append(f"{ex['n_pos']} position{'s' if ex['n_pos'] != 1 else ''} · {ex['n_orders']} open order{'s' if ex['n_orders'] != 1 else ''}"
                    + (f" · <b>{len(outside)} outside strategies</b>" if outside else " · all matched to tickets"))
    else:
        summ.append("exchange: " + ("not configured" if ex is None else "read failed"))
    for s_ in strats:
        st = s_["_stats"]
        summ.append(f"{s_['id']} {s_['mode']}: {st['SETUP']} setups · {st['FILLED']} filled · {st['STOPPED']} stop · {st['TARGET']} tgt · runner {st['cycles']}/{st['expected']}")
    summary = "\n".join(summ)

    # ---- HTML statement: results/reports + optional export ----
    html = html_statement(stamp, mode, book, strats, ex, outside)
    out_dir = REPO / "results" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"TradingBook-daily-{now:%Y-%m-%d}.html"
    fpath = out_dir / fname
    fpath.write_text(html, encoding="utf-8")
    exp = str(book.get("report", {}).get("export_dir", "") or "")
    if exp:
        import os
        try:
            ed = Path(os.path.expandvars(exp)); ed.mkdir(parents=True, exist_ok=True)
            (ed / fname).write_text(html, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"export failed: {e}", file=sys.stderr)

    if a.stdout:
        import re
        print(re.sub(r"</?b>", "", summary)); print(); print("\n".join(full)); print(f"\nstatement: {fpath}")
        return 0
    al = book.get("alerts", {})
    to, bk = al.get("daily_to", "digest"), al.get("book", "trading")
    # one message: the statement as the attachment, the summary as its caption (<= 1024 chars)
    caption = summary if len(summary) <= 1000 else summary[:990] + "…"
    telegram.send_document(fpath, caption=caption, to=to, book=bk, html_caption=True)
    print("sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
