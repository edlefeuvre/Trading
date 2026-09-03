r"""common.exchange.binance — minimal signed client for Binance USDC-margined futures.

Credentials: one env file per key under the provider folder, by name:
    %USERPROFILE%\.config\binance\<name>.env     BINANCE_KEY=...  BINANCE_SECRET=...
A strategy names its key in params.yaml (credentials.exchange: binance/SERVER_TRADING_RW).
No third-party packages. The ONLY write this client can do is cancel_order(); nothing here
places, amends or closes anything.

CLI (prints to YOUR console only; nothing leaves the machine except the signed requests):
    python -m common.exchange.binance --key SERVER_RO --test          # time, permissions, balances
    python -m common.exchange.binance --key SERVER_RO --restrictions  # what this key may do
    python -m common.exchange.binance --list
    python -m common.exchange.binance --history AVAXUSDC --hours 48   # journal: orders, fills, trade ids
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("TRADING_CONFIG_DIR", Path.home() / ".config")) / "binance"
FAPI = "https://fapi.binance.com"      # USD-M futures (USDC perps live here)
SAPI = "https://api.binance.com"       # spot/account endpoints (key restrictions)


class BinanceError(RuntimeError):
    pass


def _read_env(path: Path) -> dict:
    if not path.is_file():
        raise BinanceError(f"credentials file not found: {path}")
    out = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def list_keys() -> list[str]:
    return sorted(p.stem for p in CONFIG_DIR.glob("*.env")) if CONFIG_DIR.is_dir() else []


class Client:
    def __init__(self, name: str):
        env = _read_env(CONFIG_DIR / f"{name}.env")
        self.name = name
        self.key = env.get("BINANCE_KEY")
        self.secret = env.get("BINANCE_SECRET")
        if not self.key or not self.secret:
            raise BinanceError(f"{name}.env needs BINANCE_KEY and BINANCE_SECRET")
        self._offset_ms = 0

    # ---- transport ---------------------------------------------------------
    def _request(self, base: str, method: str, path: str, params: dict | None = None, signed: bool = False):
        params = dict(params or {})
        if signed:
            params["timestamp"] = int(time.time() * 1000) + self._offset_ms
            params["recvWindow"] = 5000
            qs = urllib.parse.urlencode(params)
            params["signature"] = hmac.new(self.secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        qs = urllib.parse.urlencode(params)
        url = f"{base}{path}" + (f"?{qs}" if qs and method in ("GET", "DELETE") else "")
        data = qs.encode() if method not in ("GET", "DELETE") and qs else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"X-MBX-APIKEY": self.key, "User-Agent": "trading-server/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            raise BinanceError(f"HTTP {e.code} {method} {path}: {body}") from e
        except urllib.error.URLError as e:
            raise BinanceError(f"network: {e.reason}") from e

    def sync_time(self) -> int:
        server = self._request(FAPI, "GET", "/fapi/v1/time")["serverTime"]
        self._offset_ms = server - int(time.time() * 1000)
        return self._offset_ms

    # ---- read-only calls ---------------------------------------------------
    def restrictions(self) -> dict:
        """What this API key is allowed to do (spot endpoint; works for any key)."""
        return self._request(SAPI, "GET", "/sapi/v1/account/apiRestrictions", signed=True)

    def futures_balances(self) -> list[dict]:
        return [b for b in self._request(FAPI, "GET", "/fapi/v2/balance", signed=True)
                if float(b.get("balance", 0)) != 0 or float(b.get("crossUnPnl", 0)) != 0]

    def positions(self) -> list[dict]:
        return [p for p in self._request(FAPI, "GET", "/fapi/v2/positionRisk", signed=True)
                if float(p.get("positionAmt", 0)) != 0]

    def income(self, hours: int = 24, income_type: str | None = None) -> list[dict]:
        """Income history for the last `hours`: REALIZED_PNL, COMMISSION, FUNDING_FEE, ... (max 1000 rows)."""
        start = int((time.time() - hours * 3600) * 1000)
        params = {"startTime": start, "limit": 1000}
        if income_type:
            params["incomeType"] = income_type
        return self._request(FAPI, "GET", "/fapi/v1/income", params, signed=True)

    # ---- the one write in this codebase: cancel an order ------------------
    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """Cancel one order by id. Needs a key with Futures permission (SERVER_TRADING_RW).
        Cancelling can only remove risk; nothing in this module places, amends or closes."""
        return self._request(FAPI, "DELETE", "/fapi/v1/order",
                             {"symbol": symbol, "orderId": int(order_id)}, signed=True)

    def open_orders(self, symbol: str | None = None) -> list[dict]:
        """Basic open orders (LIMIT, MARKET-pending). Conditional orders are NOT here — see open_algo_orders."""
        return self._request(FAPI, "GET", "/fapi/v1/openOrders", {"symbol": symbol} if symbol else None, signed=True)

    def open_algo_orders(self, symbol: str | None = None) -> list[dict]:
        """Conditional orders — Binance's 'Conditional' tab: STOP_MARKET, TAKE_PROFIT_MARKET, STOP,
        TAKE_PROFIT, TRAILING_STOP_MARKET. Since Binance moved these to its Algo Order service they no
        longer appear in /fapi/v1/openOrders. Fields: algoId, orderType, quantity, triggerPrice, price,
        workingType (MARK_PRICE | CONTRACT_PRICE), reduceOnly, closePosition."""
        p = {"algoType": "CONDITIONAL"}
        if symbol:
            p["symbol"] = symbol
        return self._request(FAPI, "GET", "/fapi/v1/openAlgoOrders", p, signed=True)

    # ---- history for the journal (read-only) -------------------------------
    def history(self, symbol: str, hours: float = 48) -> dict:
        """Everything the journal needs for one symbol: orders (basic), conditional (algo) orders,
        fills with trade ids and maker/taker flags, and income rows. Each list is best-effort —
        a failing endpoint leaves an 'errors' note rather than failing the whole call."""
        start = int((time.time() - hours * 3600) * 1000)
        out = {"symbol": symbol, "hours": hours, "orders": [], "algo_orders": [], "fills": [], "income": [], "errors": {}}
        calls = {
            "orders": ("/fapi/v1/allOrders", {"symbol": symbol, "startTime": start, "limit": 500}),
            "algo_orders": ("/fapi/v1/allAlgoOrders", {"symbol": symbol, "startTime": start, "limit": 500}),
            "fills": ("/fapi/v1/userTrades", {"symbol": symbol, "startTime": start, "limit": 1000}),
            "income": ("/fapi/v1/income", {"symbol": symbol, "startTime": start, "limit": 500}),
        }
        for k, (path, params) in calls.items():
            try:
                out[k] = self._request(FAPI, "GET", path, params, signed=True)
            except BinanceError as e:
                out["errors"][k] = str(e)
        return out


def _ts(ms) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(int(ms) / 1000)) + " UTC"


def format_history(h: dict) -> str:
    """Plain-text rendering of Client.history() for the journal."""
    L = [f"== {h['symbol']} · last {h['hours']:g}h"]
    L.append("\n-- orders (basic: limit / market / triggered stops) --")
    for o in h["orders"]:
        L.append(f"{_ts(o['time'])}  id {o['orderId']:<14} {o['side']:<4} {o['type']:<20} {o['status']:<16} "
                 f"qty {float(o['origQty']):>10g} filled {float(o['executedQty']):>10g} price {float(o['price']):>10g} "
                 f"avg {float(o.get('avgPrice', 0) or 0):>10g} stop {float(o.get('stopPrice', 0) or 0):>10g} {o.get('timeInForce', '')} "
                 f"reduceOnly={o.get('reduceOnly')} workingType={o.get('workingType', '')}  updated {_ts(o['updateTime'])}")
    L.append("\n-- conditional (algo) orders --")
    for o in h["algo_orders"]:
        L.append(f"{_ts(o['createTime'])}  algoId {o['algoId']:<12} {o['side']:<4} {o.get('orderType', ''):<20} {o.get('algoStatus', ''):<12} "
                 f"qty {float(o.get('quantity') or 0):>10g} trigger {float(o.get('triggerPrice') or 0):>10g} price {float(o.get('price') or 0):>10g} "
                 f"{o.get('workingType', '')} closePosition={o.get('closePosition')} triggeredOrderId={o.get('orderId') or o.get('triggerOrderId') or ''}"
                 f"  updated {_ts(o.get('updateTime', o['createTime']))}")
    L.append("\n-- fills (userTrades) --")
    for t in h["fills"]:
        L.append(f"{_ts(t['time'])}  trade {t['id']:<12} order {t['orderId']:<14} {t['side']:<4} qty {float(t['qty']):>10g} @ {float(t['price']):>10g} "
                 f"quote {float(t['quoteQty']):>10.2f} fee {float(t['commission']):.6f} {t['commissionAsset']} {'MAKER' if t['maker'] else 'TAKER'} "
                 f"realizedPnl {float(t['realizedPnl']):+.4f}")
    L.append("\n-- income --")
    for r in h["income"]:
        L.append(f"{_ts(r['time'])}  {r['incomeType']:<14} {float(r['income']):+.6f} {r['asset']}  {r.get('info', '')}")
    for k, e in h["errors"].items():
        L.append(f"\n({k}: not available — {e})")
    return "\n".join(L)


def _fmt_restrictions(r: dict) -> str:
    keys = ["ipRestrict", "enableReading", "enableFutures", "enableSpotAndMarginTrading",
            "enableMargin", "enableWithdrawals", "enableInternalTransfer", "permitsUniversalTransfer",
            "enableVanillaOptions", "enablePortfolioMarginTrading", "enableFixApiTrade", "enableFixReadOnly"]
    lines = []
    for k in keys:
        if k in r:
            flag = "YES" if r[k] else "no "
            warn = "  <-- must be off" if k == "enableWithdrawals" and r[k] else ""
            warn = warn or ("  <-- should be on" if k == "ipRestrict" and not r[k] else "")
            lines.append(f"  {k:<32} {flag}{warn}")
    if "createTime" in r:
        lines.append(f"  created   {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(r['createTime']/1000))}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default="SERVER_RO", help="name of <key>.env under .config/binance")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--test", action="store_true", help="time sync, restrictions, balances, positions, open orders")
    g.add_argument("--restrictions", action="store_true")
    g.add_argument("--list", action="store_true")
    g.add_argument("--history", metavar="SYMBOL", help="orders, conditional orders, fills (trade ids) and income for one symbol")
    ap.add_argument("--hours", type=float, default=48, help="lookback for --history (default 48)")
    a = ap.parse_args(argv)
    try:
        if a.history:
            c = Client(a.key)
            c.sync_time()
            print(format_history(c.history(a.history.upper(), a.hours)))
            return 0
        if a.list:
            print(f"config dir: {CONFIG_DIR}")
            print("\n".join(list_keys()) or "(no *.env files)")
            return 0
        c = Client(a.key)
        off = c.sync_time()
        print(f"key '{a.key}': server reachable, clock offset {off:+d} ms")
        r = c.restrictions()
        print("permissions:")
        print(_fmt_restrictions(r))
        if a.restrictions:
            return 0
        bal = c.futures_balances()
        print("futures balances:" if bal else "futures balances: none")
        for b in bal:
            print(f"  {b['asset']:<6} balance {float(b['balance']):>14.4f}   available {float(b['availableBalance']):>14.4f}   unPnl {float(b['crossUnPnl']):>+10.4f}")
        pos = c.positions()
        print(f"open positions: {len(pos)}")
        for p in pos:
            print(f"  {p['symbol']:<14} qty {float(p['positionAmt']):>+12.4f}  entry {float(p['entryPrice']):>12.4f}  mark {float(p['markPrice']):>12.4f}  uPnl {float(p['unRealizedProfit']):>+10.4f}  {p.get('marginType','')} {p.get('leverage','')}x")
        oo = c.open_orders()
        print(f"open orders (basic): {len(oo)}")
        for o in oo:
            print(f"  {o['symbol']:<14} {o['side']:<5} {o['type']:<12} qty {float(o['origQty']):>10.4f}  price {float(o['price']):>12.4f}  stop {float(o.get('stopPrice',0)):>12.4f}  {o.get('timeInForce','')}  id {o['orderId']}")
        ao = c.open_algo_orders()
        print(f"open orders (conditional): {len(ao)}")
        for o in ao:
            wt = "mark" if o.get("workingType") == "MARK_PRICE" else "last"
            cp = "  close-all" if str(o.get("closePosition")).lower() == "true" else ""
            print(f"  {o['symbol']:<14} {o['side']:<5} {o['orderType']:<18} qty {float(o.get('quantity') or 0):>10.4f}  price {float(o.get('price') or 0):>12.4f}  trigger {float(o.get('triggerPrice') or 0):>12.4f} ({wt})  algoId {o['algoId']}{cp}")
        return 0
    except BinanceError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
