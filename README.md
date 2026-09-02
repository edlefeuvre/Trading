# Trading — strategy server repository

One repository, many strategies, one server. Every strategy is a self-contained
folder under `strategies/` and is described, governed and change-logged by the
`STRATEGY.md` inside it. Nothing about a strategy is allowed to live only in
someone's head, a chat thread or a Telegram message.

## Hard rules

1. **Code and the strategy document change together, in the same commit.** The hook refuses otherwise.
2. **PAPER by default.** `mode: LIVE` needs `live_approved:` written by Ed in `STRATEGY.md` and a change-log row; the runner refuses without both. No agent or script ever sets it.
3. **Every message says its mode.** `PAPER · SETUP · TS01`. A message must never assert a position that was not read from the exchange in the same cycle.
4. **Secrets never enter the repo.** Bitwarden → `%USERPROFILE%\.config\<provider>\<name>.env` via `deploy\windows\sync-secrets.ps1`. No server key may withdraw or transfer.
5. **`results/` is a record.** Add to it; never rewrite it. A wrong backtest gets a new file saying so.
6. **Private repository, always.**

## Naming

```
TS<nn>_<Strategy>_<Platform>_<Universe>
TS01_CHoCH_ICT_15m_Binance_USDCp
```

| Part | Meaning | Rule |
|---|---|---|
| `TSnn` | Trading Strategy number, two digits, never reused | `TS01` is the first; a retired strategy keeps its number |
| `Strategy` | The entry family, optionally with a variant | `CHoCH_ICT`, `FundingFade`, `EMAx` … underscores allowed inside |
| `TF` | Bar timeframe the strategy was tested on | `15m`, `1H`, `4H`, `1D`. Changing it = a new strategy, new number |
| `Platform` | Where it executes | `Binance`, `Bybit`, `IBKR` … |
| `Universe` | Product set it is tested on and allowed to trade | `USDCp` = USDC-margined perpetuals. `USDTp`, `Spot`, `Opt` … |

The folder name, the systemd unit names, the log file names, the Telegram
message prefix and the heading of `STRATEGY.md` all use the **same string**.
Grep for `TS01` and you find everything TS01.

The spoken form is `TS01 CHoCH ICT 15m Binance USDCp`; the filesystem form replaces
spaces with `_` and drops the dot (`USDCp`) so it is safe in unit names, Pine
titles and Python module paths.

## Layout

```
Trading/                    (%USERPROFILE%\Repos\Trading on the PC)
├── README.md                  ← this file: the conventions
├── CLAUDE.md                  ← instructions to Claude Code on the server
├── Makefile                   ← new-strategy, check, install, status
├── .githooks/pre-commit       ← blocks code changes without a change-log entry
├── bin/                       ← repo-wide scripts (install, check, new-strategy)
├── templates/                 ← STRATEGY.md and unit templates for new strategies
├── common/                    ← shared code, NOT strategy-specific
│   ├── data/                  ← klines download / cache (data.binance.vision, ccxt)
│   ├── engine/                ← backtest engine core (locked ICT base lives here)
│   ├── exchange/              ← Binance client, reconciliation, order helpers
│   └── alerts/                ← Telegram sender, message templates
├── deploy/systemd/            ← generated unit files (what `make install` links)
└── strategies/
    └── TS01_CHoCH_ICT_15m_Binance_USDCp/
        ├── STRATEGY.md        ← THE document. Spec, params, artefact register, change log
        ├── config/            ← params.yaml (the only place numbers live), universe.yaml
        ├── pine/              ← TradingView scripts, one file per indicator/strategy
        ├── src/               ← runner.py (live/paper), backtest.py, tests/
        ├── systemd/           ← this strategy's .service / .timer
        ├── results/           ← backtest outputs, dated, committed (small CSV/MD only)
        └── logs/              ← runtime logs, git-ignored
```

`common/` is shared plumbing. If a change in `common/` alters how any strategy
behaves (fees, fill model, reconciliation), **every affected strategy's
`STRATEGY.md` gets a change-log line** saying so. The hook enforces this for
`common/engine` and `common/exchange`.

## The one rule

**Code and the document change together, in the same commit.**

Any commit that touches `strategies/TSnn/{pine,src,config}/` or
`common/{engine,exchange}/` must also add a line to the **Change log** table of
the affected `STRATEGY.md`. The pre-commit hook (`.githooks/pre-commit`, enabled
by `make hooks`) refuses the commit otherwise. The change-log line names the
files touched, so the document is the index into the code history, not a
parallel narrative that drifts from it.

Versioning: `STRATEGY.md` carries `version: MAJOR.MINOR`.

- **MAJOR** — the tested spec changed (entry, exit, stop, universe, timeframe,
  fee model). Old backtests no longer describe this strategy; re-run and record.
- **MINOR** — implementation, alerting, ops, parameters within a declared range,
  documentation. Backtests remain valid.

The Pine `//@version`-adjacent header comment and the Python `__version__`
carry the same number.

## Modes

Every runner has exactly one of three modes, set in `config/params.yaml` and
echoed as the first token of every alert:

| Mode | Places orders? | Purpose |
|---|---|---|
| `PAPER` | No | Detection, paper fills, lifecycle alerts. Default. |
| `SHADOW` | No | Everything PAPER does, plus it composes the exact live ticket and logs it — dress rehearsal |
| `LIVE` | Yes | Only after the gate in `STRATEGY.md` §7 is recorded as cleared |

A strategy folder cannot be promoted to `LIVE` by editing the yaml alone: the
runner refuses to start LIVE unless `STRATEGY.md` frontmatter has
`live_approved: <date>` **and** the date is present in the change log.

## Operations

```
make new TS=02 NAME=FundingFade TF=1H PLATFORM=Binance UNIVERSE=USDCp   # scaffold
make check                    # runs the doc/code consistency check on all strategies
make hooks                    # installs the pre-commit hook
make install TS=01            # links + enables that strategy's systemd units
make status                   # systemctl status for every TS* unit
make logs TS=01               # journalctl -fu for that strategy
```

Everything runs as the `trader` user under systemd, logs to journald, and
strategy-level files go to `strategies/TSnn/logs/`. When this moves to
Paperclip, the units are the contract: one runner process per strategy, one
scheduled job per timer, environment from `/etc/trading/TSnn.env`.

## Secrets

Never in the repo. `/etc/trading/<TSnn>.env`, mode 600, owned by `trader`:
trade-only keys, withdrawals disabled, IP-allowlisted. `.gitignore` refuses
`*.env`, `logs/`, and anything under `data/cache/`.

## Mirror to the Claude "Trading" project

The repo `STRATEGY.md` is canonical. Inside the repo the folder carries the
identity, so the file is just `STRATEGY.md`. **Anywhere the file stands alone it
carries the full slug**: the Claude project copy is
`claude/<slug>-STRATEGY.md` (e.g. `TS01_CHoCH_ICT_15m_Binance_USDCp-STRATEGY.md`)
and the OneDrive export is `TRA\10_Strategies\<slug>\<slug>-STRATEGY.md`, with
weekly outputs beside it as `<slug>-weekly-<date>.md`. Copies are read-only by
convention: edits go to the repo, then get re-mirrored at the Sunday pass or
after any MAJOR bump.
