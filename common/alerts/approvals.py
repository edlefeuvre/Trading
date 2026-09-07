r"""common.alerts.approvals — Ed's Apply / Hold / Re-run buttons, and the 'approved' reply.

The Sunday programme posts a `PAPER · APPROVAL · TS01` message to the 00 Approvals topic with an
inline keyboard. A press reaches Telegram as a callback_query; a typed reply ('approved', 'hold',
'approved <id>') reaches it as a message. Both are Telegram *updates*, and whichever process owns
the bot's webhook receives them — on the server that is the Paperclip webhook (never write to
%USERPROFILE%\.config\telegram-webhook\; Paperclip owns it). That process calls

    from common.alerts.approvals import handle_update
    result = handle_update(update_json, repo_root=r"C:\Users\Admin\Repos\Trading")

and this module does the rest: checks the press is Ed's, runs the strategy's `weekly --apply`
/ `--hold` / `--run-now`, and edits the message. `result` is a dict for the webhook's log.

When no webhook is set on the bot (a test bot, or the webhook is down), `python -m
common.alerts.approvals --poll` long-polls getUpdates and handles the same updates itself.
Telegram refuses getUpdates while a webhook exists, so the two never compete.

Authorisation: the owner id in the telegram env files (.config\telegram\trading.env or the bot file) under
TELEGRAM_OWNER_ID / OWNER_ID / OwnerID (any case). A press or
reply from anyone else is acknowledged with a toast and ignored. Nothing here changes params.yaml
or the spec; the only write is what `weekly --apply` does, and that refuses an expired proposal or
a params hash that no longer matches.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):            # Windows consoles default to cp1252; the reviews carry → — ·
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from common.alerts import telegram

REPO = Path(__file__).resolve().parent.parent.parent
CALLBACK = re.compile(r"^(?P<ts>ts\d{2}):(?P<action>apply|hold|rerun)(?::(?P<id>[0-9a-f]{6,16}))?$")
REPLY = re.compile(r"^\s*(?P<action>approved?|apply|hold|rerun|re-run)\b\s*(?P<id>[0-9a-f]{6,16})?\s*$", re.I)


def strategy_module(ts: str, repo: Path) -> str | None:
    for d in (repo / "strategies").glob(f"{ts.upper()}_*"):
        if (d / "src" / "weekly.py").is_file():
            return f"strategies.{d.name}.src.weekly"
    return None


def run_weekly(ts: str, args: list[str], repo: Path, timeout: int = 1800) -> tuple[int, str]:
    mod = strategy_module(ts, repo)
    if not mod:
        return 2, f"no strategy folder for {ts}"
    cmd = [sys.executable, "-m", mod, *args]
    r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    out = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode, out or r.stderr.strip()[-300:]


OWNER_KEYS = ("telegram_owner_id", "owner_id", "ownerid", "telegram_owner", "owner")


def owner_id(bot: telegram.Bot) -> str | None:
    """Ed's numeric Telegram user id, from the address book or the bot file. Accepts the key under any of
    OWNER_KEYS, case-insensitively — Ed keeps it as `OwnerID=` in the telegram env (added for exactly this)."""
    env = {}
    for name in ([bot.book] if bot.book else []) + [bot.name]:
        try:
            env.update(telegram._read_env(telegram.CONFIG_DIR / f"{name}.env"))
        except telegram.TelegramError:
            pass
    env.update({k: v for k, v in os.environ.items() if k.lower() in OWNER_KEYS})
    for k, v in env.items():
        if k.lower() in OWNER_KEYS and v.strip().isdigit():
            return v.strip()
    return None


def _find_id_in_text(text: str) -> tuple[str | None, str | None]:
    """(ts, proposal id) from an approval message body ('PAPER · APPROVAL · TS01 …  id abc123')."""
    m_ts = re.search(r"APPROVAL · (TS\d{2})", text or "")
    m_id = re.search(r"\bid ([0-9a-f]{6,16})\b", text or "")
    return (m_ts.group(1) if m_ts else None), (m_id.group(1) if m_id else None)


def handle_update(update: dict, repo_root: str | Path = REPO, bot: telegram.Bot | None = None,
                  book: str = "trading", bot_name: str = "rickyassist_bot", runner=run_weekly) -> dict:
    """Handle one Telegram update. Returns {"handled": bool, "action": ..., "result": ...}."""
    repo = Path(repo_root)
    bot = bot or telegram.Bot(bot_name, book=book)
    owner = owner_id(bot)

    cq = update.get("callback_query")
    if cq:
        m = CALLBACK.match(cq.get("data", ""))
        if not m:
            return {"handled": False, "reason": "not an approvals callback"}
        if not owner or str(cq.get("from", {}).get("id")) != str(owner):
            bot.answer_callback(cq["id"], "Not yours to press.", alert=True)
            return {"handled": True, "action": m["action"], "result": "refused: not owner"}
        ts, action, pid = m["ts"], m["action"], m["id"]
        bot.answer_callback(cq["id"], {"apply": "Applying…", "hold": "Holding…", "rerun": "Re-running the Sunday programme…"}[action])
        msg = cq.get("message") or {}
        return _act(ts, action, pid, bot, repo, runner, msg.get("chat", {}).get("id"), msg.get("message_id"), msg.get("text", ""))

    msg = update.get("message") or update.get("edited_message")
    if msg and msg.get("text"):
        m = REPLY.match(msg["text"])
        parent = msg.get("reply_to_message") or {}
        if not m or "APPROVAL" not in (parent.get("text") or ""):
            return {"handled": False, "reason": "not an approval reply"}
        if not owner or str(msg.get("from", {}).get("id")) != str(owner):
            return {"handled": True, "result": "refused: not owner"}
        ts, pid_in_msg = _find_id_in_text(parent.get("text", ""))
        action = {"approved": "apply", "approve": "apply", "apply": "apply", "hold": "hold", "rerun": "rerun", "re-run": "rerun"}[m["action"].lower()]
        return _act(ts or "TS01", action, m["id"] or pid_in_msg, bot, repo, runner,
                    parent.get("chat", {}).get("id"), parent.get("message_id"), parent.get("text", ""))
    return {"handled": False, "reason": "not relevant"}


def _act(ts, action, pid, bot, repo, runner, chat_id, message_id, original_text) -> dict:
    if action == "rerun":
        code, out = runner(ts, ["--run-now"], repo)
        note = "🔄 re-run started — see the new Digest / Approvals messages" if code == 0 else f"❌ re-run failed: {out}"
    else:
        args = ["--apply" if action == "apply" else "--hold"] + (["--proposal", pid] if pid else [])
        code, out = runner(ts, args, repo)
        note = out if out else ("done" if code == 0 else "failed")
    if chat_id and message_id and action != "rerun":
        try:
            bot.edit(chat_id, message_id, (original_text or "").split("\n\n✅")[0].split("\n\n⏸")[0] + "\n\n" + note,
                     buttons=None if code == 0 else _keyboard_from(original_text, ts, pid))
        except telegram.TelegramError as e:
            print(f"edit failed: {e}", file=sys.stderr)
    return {"handled": True, "action": action, "proposal": pid, "code": code, "result": out}


def _keyboard_from(text, ts, pid):
    """Keep the buttons after a failed apply so Ed can retry."""
    if not pid:
        return None
    t = ts.lower()
    return [[("✅ Apply", f"{t}:apply:{pid}"), ("⏸ Hold", f"{t}:hold:{pid}")], [("🔄 Re-run", f"{t}:rerun")]]


def poll(bot_name: str, book: str, repo: Path, once: bool = False) -> int:
    """getUpdates loop for bots WITHOUT a webhook. Offsets are kept in .config/telegram/<bot>.offset."""
    bot = telegram.Bot(bot_name, book=book)
    off_file = telegram.CONFIG_DIR / f"{bot_name}.offset"
    offset = int(off_file.read_text()) if off_file.is_file() else 0
    print(f"polling @{bot.me()['username']} as owner {owner_id(bot) or 'UNSET — set TELEGRAM_OWNER_ID'}")
    while True:
        try:
            updates = bot._call("getUpdates", offset=offset, timeout=25, allowed_updates=json.dumps(["message", "callback_query"]))
        except telegram.TelegramError as e:
            print(f"getUpdates: {e}", file=sys.stderr); time.sleep(5); continue
        for u in updates:
            offset = u["update_id"] + 1
            res = handle_update(u, repo, bot=bot)
            if res.get("handled"):
                print(json.dumps(res))
        off_file.write_text(str(offset))
        if once:
            return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bot", default="rickyassist_bot")
    ap.add_argument("--book", default="trading")
    ap.add_argument("--repo", default=str(REPO))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--poll", action="store_true", help="long-poll getUpdates (only when the bot has no webhook)")
    g.add_argument("--once", action="store_true", help="one getUpdates pass, then exit")
    g.add_argument("--handle", metavar="JSON", help="handle one update given as JSON (what a webhook would pass)")
    a = ap.parse_args(argv)
    if a.handle:
        print(json.dumps(handle_update(json.loads(a.handle), a.repo, book=a.book, bot_name=a.bot), indent=1)); return 0
    return poll(a.bot, a.book, Path(a.repo), once=a.once)


if __name__ == "__main__":
    sys.exit(main())
