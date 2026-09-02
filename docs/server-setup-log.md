# Trading server — setup log and decisions

_Started 2 Sep 2026. The record of how the Windows PC is laid out and why. Update
at each stage; the repo's `MIGRATION.md` carries the how-to, this carries the why._

## The machine

High-spec Windows 11 PC, accessed by Remote Desktop, on Tailscale. Runs
PaperclipAI, TradingView Desktop, Claude Code, native Python 3.12. It is the
"server". Everything trading-related runs natively on Windows under Task
Scheduler (decision 2 Sep: WSL2 was considered and rejected — Paperclip and
every existing job already run native Python via Task Scheduler; one runtime,
one scheduler).

## Naming (settled 2 Sep, evening)

`TS<nn>_<Strategy>_<TF>_<Platform>_<Universe>` — e.g. `TS01_CHoCH_ICT_15m_Binance_USDCp`.
First token ID, last three TF/Platform/Universe, the middle is the strategy name
(underscores allowed). Timeframe is in the name because a new timeframe is a new
strategy (new number) and Ed wants to tell them apart at a glance in Telegram.

## Layout decisions (2 Sep 2026)

| Thing | Where | Why |
|---|---|---|
| Code and STRATEGY.md | `C:\Users\Admin\Repos\Trading` — a git repo, GitHub as remote/backup | `Repos\` is the one root for every repository (PaperclipAI already there); nothing in git lives under OneDrive |
| Documents Ed reads on the phone | `OneDrive\TRA` (exports only, never a source) | OneDrive renders Markdown; GitHub app is the alternative but Ed prefers OneDrive |
| Runtime secrets | `%USERPROFILE%\.config\<provider>\<name>.env` — `telegram\rickyassist_bot.env`, `binance\readonly.env`, `binance\futures-trade.env` … | Same convention the GARCH launcher already used (`.config\telegram-webhook\secrets.env`) |
| Master of secrets | Bitwarden (free account), folder per provider, one Secure-note item per key/bot, single Hidden field per secret + Text fields for audit (`Username`, `Ownership`, `Rotated`, note `used_by`) | Rotate from the phone; PC pulls with `deploy\windows\sync-secrets.ps1` (hourly task optional) |
| Telegram address books | Bitwarden items per purpose in the `telegram` folder — `trading` (later `investments`, `paperclipai`) — synced to `.config\telegram\trading.env`. Fields `TELEGRAM_TO_<ROLE>=<chat>_<topic>` (Telegram's own notation). Bot items hold only the token | Destinations are shared by all bots and Ed wants to edit them from the phone; role names stay stable when topics are renamed/renumbered |
| PaperclipAI | Not in the loop for the trading bots yet. Its scheduler is internal (heartbeats), so it cannot be the supervisor; if adopted later it sits above as auditor/watcher | Bots need no AI; systemd-equivalent (Task Scheduler) must survive Paperclip being down |
| Paperclip companies TRA/INV split | Deferred | Ricky is one bot with one webhook; splitting now buys nothing |

**Never write to** `.config\telegram-webhook\secrets.env` — Paperclip rewrites it
every 15 min (its `PAPERCLIP_API_KEY` is a rotating session JWT). Our sync only
writes under `.config\<provider>\` for providers it is given, and refuses
`telegram-webhook` and `bitwarden`.

## Telegram

One bot, `@RickyAssist_Bot` (Ricky). Forum group **RickyAI Investments
Assistant** (`-1003939412847`, may be renamed "Wealth Assistant"); topics
(number prefixes are ordering labels, not ids): Approvals, Market Intelligence
(GARCH 07:00), Portfolio, Crypto (TS01 lifecycle), Brokerage (future IBKR),
Digest (Sunday review, journal summaries), Alerts (CANCEL NOW, STATE MISMATCH,
STOPPED, BLOCKED). Second group **Ricky Logs** (`-1003992348394`, auto-delete 2
months): Emails, Investments, Actions, Systems (heartbeat, WEEKLY FAILED,
secrets-sync), Session, General.

The `trading` address book (Bitwarden → `.config\telegram\trading.env`):
`TELEGRAM_TO_TRADING=-1003939412847_4`, `_ALERTS=…_54`, `_DIGEST=…_56`,
`_APPROVALS=…_6`, `_SYSLOG=-1003992348394_11`, `_ACTIVITY_LOG=…_13`.

Rules: if a message expires harmlessly it goes to Logs; if it would matter in a
month it goes to the Investments group. Per-cycle activity goes to a local JSONL
log, Telegram gets state changes plus a heartbeat; ACTIVITY_LOG receives a
rollup, not the raw stream. Strategies name destinations in `params.yaml`
(`alerts.book: trading`, `to: trading`, `critical_to: alerts`,
`weekly_to: digest`, `approvals_to: approvals`); code says `send(text, to="alerts")`. Inbound (Ed's replies) goes through Paperclip's webhook
receiver, so it stops when Paperclip is down — critical alerts must therefore
tell Ed what to do at the exchange rather than wait for a reply.

## What exists on the PC today (Stage 1 findings)

- `CHoCH watcher` — Task Scheduler, every 15 min on the quarter hour, `python
  choch_watch.py` in `C:\Users\Admin\choch` (two files, not in git; engine
  functions copied verbatim from the backtest engine; K=5, LIVE_BARS=32, 1500
  bars/run, sizing max(1% book, $20) with per-symbol multipliers from
  `.choch-watch\sizes.json`), 10-min limit, no restart, logon type Interactive. This is Ricky's detection loop → becomes
  `strategies\TS01_CHoCH_ICT_15m_Binance_USDCp\src\runner.py`.
- `GarchDailyDeliver` — Task Scheduler 07:00, PowerShell launcher in
  `C:\Users\Admin\investment-portfolio\scripts\`, own venv, logs to
  `logs\garch-deliver.log`, secrets from `telegram-webhook\secrets.env`.
  Investment-book code; its own repo `github.com/edlefeuvre/investment-portfolio`
  (private; last push was 4 months behind the working copy on 2 Sep). Also holds
  `hedge-book-daily.js`, `data\hedge-ledger.jsonl`, the Board conventions
  (`config\conventions\` — Paperclip project naming `[ASSET_CLASS]-[account]-[Type]`,
  asset classes by dominant risk driver) and the firm README with Hard Rules.
  Its `strategies\{active,archived,watchlist}` are empty → `STRATEGY.md` becomes the
  strategy format for both repos. Working copy is full of Paperclip agent scratch
  (payload/response JSON in `logs\` and the repo root) — ignore-listed on 2 Sep, not committed.
  To move under `Repos\` later (update the three task paths).
- `TelegramWebhookRickyAI` — Task Scheduler (Running): `investment-portfolio\scripts\telegram-webhook-launcher.ps1`
  → `telegram-webhook-server.js` (Node). **This is Ricky's inbound receiver.** It forwards
  Ed's Telegram messages to the Paperclip agent using the JWT in `telegram-webhook\secrets.env`
  (rewritten by Paperclip every 15 min; lapse post-mortem: `docs\decisions\INV-522-…`).
  Health check: `INV-WebhookMonitor` task → `telegram-webhook-monitor.ps1`.
- `INV-SnapshotRefresh` — disabled; runs Node code from `OneDrive\INV\scripts\` (code in OneDrive — to retire).
- `Paperclip*` tasks — Paperclip's own pollers/webhook receiver; leave alone.
- Both trading tasks are Interactive → **auto-logon is required** for anything
  to run after a reboot.

## Relationship to the Investment Portfolio conventions

TS names systems; the Board convention names mandates (Paperclip projects). A
mandate holds several systems; a system belongs to one mandate, recorded as
`mandate:` in `STRATEGY.md` frontmatter (e.g. `CRYPTO-binance-<Type>` for TS01;
Type to be chosen by Ed). Mandate names keep `-`/`_` separators; TS folders are
underscores-only because they are Python package paths. To adopt from the firm
repo: a repo-level `config/risk-policy.yaml` (Board-only, per-strategy caps must
fit inside it, checked by `make check`), append-only `results/` enforced by the
hook, and a Hard Rules block in the README.

## Stage status

- Stage 1 — auto-logon + power/update settings; find GARCH and CHoCH tasks: findings above; auto-logon to confirm.
- Stage 2 — Telegram sender + Bitwarden sync + `trading` address book: **done 2 Sep** (test into the Crypto topic via `--to trading`).
- Stage 3 — Binance key audit → Bitwarden items (`binance/readonly`, `binance/futures-trade`); `choch` code review (`choch_watch.py`, `choch_sizes.py`, `.choch-watch\{sizes,state,telegram}.json` — telegram.json is a third token copy, to be retired).
- Stage 4 — Windows conversion of the scaffold (Task Scheduler XML, `install.ps1`), migrate `choch` → TS01 runner with reconciliation loop and the five replay tests.
- Stage 5 — GitHub repo `Trading`, first push; Sunday programme exporting to `OneDrive\TRA`.
