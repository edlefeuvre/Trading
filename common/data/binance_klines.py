r"""common.data.binance_klines — 15m bars for Binance USD-M futures (USDC perps).

Two sources, moved from choch_watch.py (live) and choch_sizes.py (archive) on 2 Sep 2026:

    klines(symbol, interval, limit, end_time)   live REST, drops the in-progress candle
    klines_paged(symbol, total, interval)       pages backwards past the 1500-bar cap
    history(symbol, start=(2024, 1), cache=...) full archive from data.binance.vision, cached
                                                per month as .pkl.gz (archive files never change)

Bars: dict(t=ms, o, h, l, c[, v]). No keys needed for any of this.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import json
import os
import pickle
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

HOSTS = ["https://fapi.binance.com/fapi/v1/klines",
         "https://fapi1.binance.com/fapi/v1/klines",
         "https://fapi2.binance.com/fapi/v1/klines"]
ARCHIVE = "https://data.binance.vision/data/futures/um"
DEFAULT_CACHE = Path(os.environ.get("TRADING_DATA_CACHE", Path.home() / ".config" / "trading-data"))


# ------------------------------------------------------------------ live ---
def klines(symbol: str, interval: str = "15m", limit: int = 1500, end_time: int | None = None) -> list[dict]:
    err = None
    for host in HOSTS:
        try:
            p = dict(symbol=symbol, interval=interval, limit=min(limit, 1500))
            if end_time is not None:
                p["endTime"] = int(end_time)
            req = urllib.request.Request(host + "?" + urllib.parse.urlencode(p),
                                         headers={"User-Agent": "trading-server/0.1"})
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = json.load(r)
            now = time.time() * 1000
            bars = []
            for z in raw:
                t, o, h, l, c, v = z[0], float(z[1]), float(z[2]), float(z[3]), float(z[4]), float(z[5])
                if z[6] >= now:            # drop the in-progress candle
                    continue
                if t > 1e14:               # microsecond timestamps in some feeds
                    t //= 1000
                bars.append(dict(t=t, o=o, h=h, l=l, c=c, v=v))
            return bars
        except Exception as e:  # noqa: BLE001 — try the next host
            err = e
    raise RuntimeError(f"could not fetch {symbol}: {err}")


def klines_paged(symbol: str, total: int, interval: str = "15m") -> list[dict]:
    """Page backwards to assemble more than the 1500-bar API cap."""
    out, end = [], None
    while len(out) < total:
        chunk = klines(symbol, interval=interval, end_time=end)
        if not chunk:
            break
        out = chunk + out
        end = chunk[0]["t"] - 1
        if len(chunk) < 1400:
            break
    return out[-total:] if total < len(out) else out


# --------------------------------------------------------------- archive ---
def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "trading-server/0.1"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def _parse_zip(blob: bytes) -> list[dict]:
    bars = []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = z.namelist()[0]
        for row in csv.reader(io.TextIOWrapper(z.open(name), "utf-8")):
            if not row or not row[0].strip().replace(".", "").isdigit():
                continue  # header line in some archives
            t = int(float(row[0]))
            if t > 1e14:
                t //= 1000
            bars.append(dict(t=t, o=float(row[1]), h=float(row[2]), l=float(row[3]), c=float(row[4])))
    return bars


def month(sym: str, y: int, m: int, interval: str = "15m", cache: Path = DEFAULT_CACHE) -> list[dict]:
    """One complete month, cached permanently — archive files never change."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{sym}-{interval}-{y}-{m:02d}.pkl.gz"
    if path.exists():
        with gzip.open(path, "rb") as f:
            return pickle.load(f)
    url = f"{ARCHIVE}/monthly/klines/{sym}/{interval}/{sym}-{interval}-{y}-{m:02d}.zip"
    try:
        bars = _parse_zip(_get(url))
    except Exception:  # noqa: BLE001 — not listed yet, or month unavailable
        bars = []
    with gzip.open(path, "wb") as f:
        pickle.dump(bars, f)
    return bars


def day(sym: str, d: dt.date, interval: str = "15m", cache: Path = DEFAULT_CACHE) -> list[dict]:
    """One day from the daily archive — used for the current partial month."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{sym}-{interval}-{d.isoformat()}.pkl.gz"
    if path.exists():
        with gzip.open(path, "rb") as f:
            return pickle.load(f)
    url = f"{ARCHIVE}/daily/klines/{sym}/{interval}/{sym}-{interval}-{d.isoformat()}.zip"
    try:
        bars = _parse_zip(_get(url))
    except Exception:  # noqa: BLE001 — today, or not published yet: do not cache
        return []
    with gzip.open(path, "wb") as f:
        pickle.dump(bars, f)
    return bars


def history(sym: str, start: tuple[int, int] = (2024, 1), interval: str = "15m",
            cache: Path = DEFAULT_CACHE, verbose: bool = True) -> list[dict]:
    """Full history from `start` (year, month) to yesterday, deduplicated on timestamp."""
    today = dt.datetime.now(dt.timezone.utc).date()
    bars = []
    y, m = start
    while (y, m) < (today.year, today.month):
        bars += month(sym, y, m, interval, cache)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    d = today.replace(day=1)
    while d < today:
        bars += day(sym, d, interval, cache)
        d += dt.timedelta(days=1)
    bars.sort(key=lambda b: b["t"])
    out, last = [], -1
    for b in bars:
        if b["t"] != last:
            out.append(b); last = b["t"]
    if verbose:
        print(f"  {sym:<14} {len(out):>7} bars", file=sys.stderr)
    return out
