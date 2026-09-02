# common — shared plumbing

Nothing in here knows about a specific strategy. Each sub-package has a README
that states what it does and which strategies depend on it.

| Package | Role | Change rule |
|---|---|---|
| `data/` | klines + funding download and cache (data.binance.vision, ccxt) | MINOR unless the data itself changes |
| `engine/` | backtest engine — the locked ICT base with pool exit lives here | **any behavioural change adds a change-log row to every strategy's STRATEGY.md** (hook-enforced) |
| `exchange/` | Binance USDC-perp client, order helpers, reconciliation | same as engine |
| `alerts/` | Telegram sender + the message contract | contract changes: row in every strategy |

Migration targets (2 Sep 2026): the locked ICT base engine → `engine/`; the
Ricky AI bot's exchange and Telegram code → `exchange/` and `alerts/`; the
bot's TS01-specific detection and lifecycle → `strategies/TS01_*/src/runner.py`.
