# common/alerts — the message contract

Source: "Ricky AI — Telegram alert specification", 2 Sep 2026 (Trading project,
`claude/ricky-ai-alert-spec.md`). This README is the normative summary; the
templates live beside it in `templates.py` once migrated.

## The one rule

**A message must never assert a position that has not been confirmed against
the exchange in the same cycle.** Reconcile first; on mismatch emit
`⚠ STATE MISMATCH`, set internal state to the exchange's answer, take no other
action this cycle.

## Message shape

```
<MODE> · <EVENT> · <TSnn> <variant>
<SYMBOL> <SIDE> <tf> · signal <dd Mon HH:MM UTC>
<body>
```

`MODE` ∈ `LIVE` | `SHADOW` | `PAPER`. If undeterminable → `PAPER` + warning.
Events: `SETUP`, `ARMED` (LIVE only, after ack), `FILLED`, `IN POSITION`,
`POOL CONSUMED · CANCEL NOW`, `TARGET HIT`, `STOPPED`, `WINDOW EXPIRED · CANCEL`,
`EXPIRING`, `BLOCKED`, `⚠ STATE MISMATCH`.

Rules carried by every runner:

- Unrealised R is from the **actual fill**; with no fill the field is omitted.
- `FILLED` states role (MAKER/TAKER), fee, drift vs plan, and **recomputed 1R**.
- Size line names the rule (`ETH 50%`), not the arithmetic.
- `SETUP` shows margin required and available.
- Pool reached **before** fill → cancel; **after** fill → `TARGET HIT`. Never
  conflate.
- Evaluate stop/target/pool/window on every bar close.

## Bots and credentials (added 2 Sep 2026)

One env file per bot, by name, in the provider folder:
`%USERPROFILE%\.config\telegram\<bot>.env` with `TELEGRAM_BOT_TOKEN`; addresses
come from the shared `addresses.env` (below). `rickyassist_bot` is the first; other bots are added
with `deploy/windows/setup-telegram.ps1 -Bot <name> -Token <token>`. Bitwarden
mirrors this: folder `telegram`, one item per bot, hidden fields named as above.

Strategies reference a bot in `params.yaml`:

```yaml
credentials:
  exchange: binance/SERVER_TRADING_RW
  telegram: telegram/rickyassist_bot
```

Sending: `from common.alerts.telegram import send; send(text, bot="rickyassist_bot")`.
Plain text, no parse mode (so `R`, `_`, `*` in messages are safe); auto-split at
4096 chars; retries on 429/network. CLI: `--test`, `--discover`, `--send`, `--list`.

Receiving (Ricky answering you) stays on the existing webhook receiver for now;
it will move under `common/alerts/inbound.py` when the runner is migrated.

WhatsApp: possible later via Meta's Cloud API or Twilio, but outbound
notifications there need an approved business account and message templates;
Telegram remains the operational channel.

## Address books (settled 2 Sep 2026, evening)

Destinations are grouped by **purpose**, one Bitwarden item each in the `telegram`
folder, synced to `.config\telegram\<item>.env`: `trading`, `investments`,
`paperclipai`, ... Each field is a complete destination in Telegram's own
notation `<chat>_<topic>` (topic optional):

```
# .config\telegram\trading.env   <- Bitwarden item telegram/trading
TELEGRAM_TO_TRADING=-1003939412847_4       # lifecycle alerts (the Crypto topic)
TELEGRAM_TO_ALERTS=-1003939412847_54       # CANCEL NOW, STATE MISMATCH, STOPPED, BLOCKED
TELEGRAM_TO_DIGEST=-1003939412847_56       # Sunday review, journal summaries
TELEGRAM_TO_APPROVALS=-1003939412847_6     # requests for Ed's decision
TELEGRAM_TO_SYSLOG=-1003992348394_<n>      # Ricky Logs / Systems: heartbeat, WEEKLY FAILED, secrets-sync
```

Field names are roles (`TRADING`, `ALERTS`); values are the numbers. Rename or
reorder a topic in Telegram and nothing changes; renumber and only the value does.
Lower-case fields become comments (use them for the human label).

Bot items hold only `TELEGRAM_BOT_TOKEN`. Code: `send(text, to="alerts")` (book
`trading`, bot Ricky by default) or `Bot("rickyassist_bot", book="investments").send(text, to="portfolio")`.
CLI: `--show` (books and destinations), `--test --to trading`, `--topics` / `--discover` to find numbers.

## Approvals — Ed's buttons (v1.30, 7 Sep 2026)

`common/alerts/approvals.py`. The Sunday programme posts `PAPER · APPROVAL · TS01` to the
Approvals topic with an inline keyboard **Apply / Hold / Re-run** (`callback_data`
`ts01:apply:<proposal id>` etc.). A press, or a reply of `approved` / `hold` / `approved <id>`
to that message, is authorised against `TELEGRAM_OWNER_ID` (put Ed's numeric Telegram user id in
the `trading.env` address book, Bitwarden item `telegram/trading`) and runs the strategy's
`weekly --apply|--hold --proposal <id>` or `weekly --run-now`; the message is edited with the
outcome. Anyone else gets a toast and nothing happens.

Where the update arrives: whichever process owns the bot's webhook — on the server that is
Paperclip's webhook, which must call

```python
from common.alerts.approvals import handle_update
handle_update(update_json, repo_root=r"C:\Users\Admin\Repos\Trading")
```

(this repo never writes to `%USERPROFILE%\.config\telegram-webhook\`). For a bot with no
webhook set, `python -m common.alerts.approvals --poll` long-polls `getUpdates` instead;
Telegram refuses `getUpdates` while a webhook exists, so the two cannot both run.

Sender additions for this: `Bot.send(..., buttons=[[("label", "callback_data")]])`,
`Bot.edit(chat_id, message_id, text, buttons=None)`, `Bot.answer_callback(id, text)`.
