r"""common.alerts.telegram — send messages through any registered Telegram bot.

Credentials: one env file per bot, by name, under the provider folder
    %USERPROFILE%\.config\telegram\<bot>.env      (Windows)
    ~/.config/telegram/<bot>.env                  (Linux/WSL)
containing
    TELEGRAM_BOT_TOKEN=123456:ABC...
    TELEGRAM_CHAT_ID=-1001234567890      # default destination; can be overridden per call

Strategies reference a bot by name in params.yaml (credentials.telegram: telegram/rickyassist_bot).
Nothing here reads the token from anywhere else. No third-party packages.

CLI:
    python -m common.alerts.telegram --bot rickyassist_bot --test
    python -m common.alerts.telegram --bot rickyassist_bot --discover     # print chat ids seen by getUpdates
    python -m common.alerts.telegram --bot rickyassist_bot --send "text"  [--chat ID] [--topic NAME|ID]
    python -m common.alerts.telegram --bot rickyassist_bot --topics       # list topic ids seen (post in each topic first)
    python -m common.alerts.telegram --list

Address books - one per purpose, shared by all bots, not secret. Item `trading` in the
Bitwarden telegram folder becomes %USERPROFILE%\.config\telegram\trading.env:
    TELEGRAM_TO_TRADING=-1003939412847_4      # <chat>_<topic>  (Telegram's own notation)
    TELEGRAM_TO_ALERTS=-1003939412847_54
    TELEGRAM_TO_DIGEST=-1003939412847_56
    TELEGRAM_TO_APPROVALS=-1003939412847_6
    TELEGRAM_TO_SYSLOG=-1003992348394         # a whole group, no topic
Bot files hold only the token. Callers name the book and the destination:
    send(text, book="trading", to="alerts")
    python -m common.alerts.telegram --book trading --to trading --test
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("TRADING_CONFIG_DIR", Path.home() / ".config")) / "telegram"
API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4096


class TelegramError(RuntimeError):
    pass


def _read_env(path: Path) -> dict:
    if not path.is_file():
        raise TelegramError(f"credentials file not found: {path}")
    out = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def list_bots() -> list[str]:
    if not CONFIG_DIR.is_dir():
        return []
    return sorted(p.stem for p in CONFIG_DIR.glob("*.env"))


def list_books() -> list[str]:
    """Address books = env files in the telegram folder that contain TELEGRAM_TO_* and no token."""
    out = []
    for p in sorted(CONFIG_DIR.glob("*.env")) if CONFIG_DIR.is_dir() else []:
        env = _read_env(p)
        if any(k.startswith("TELEGRAM_TO_") for k in env) and not env.get("TELEGRAM_BOT_TOKEN"):
            out.append(p.stem)
    return out


class Bot:
    def __init__(self, name: str, book: str | None = None):
        self.name = name
        self.book = book
        env = {}
        if book:
            env.update(_read_env(CONFIG_DIR / f"{book}.env"))       # address book: TELEGRAM_TO_*
        env.update(_read_env(CONFIG_DIR / f"{name}.env"))           # bot file: token (+ optional overrides)
        self.dests = {k[len("TELEGRAM_TO_"):].lower(): v for k, v in env.items() if k.startswith("TELEGRAM_TO_")}
        self.token = env.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_RICKYASSIST_BOT_TOKEN")
        self.default_chat = env.get("TELEGRAM_CHAT_ID")
        self.chats = {k[len("TELEGRAM_CHAT_"):].lower(): v for k, v in env.items()
                      if k.startswith("TELEGRAM_CHAT_") and k != "TELEGRAM_CHAT_ID"}
        self.topics = {k[len("TELEGRAM_TOPIC_"):].lower(): v for k, v in env.items() if k.startswith("TELEGRAM_TOPIC_")}
        if not self.token:
            raise TelegramError(f"{name}.env has no TELEGRAM_BOT_TOKEN")

    def _call(self, method: str, **params) -> dict:
        data = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
        req = urllib.request.Request(API.format(token=self.token, method=method), data=data)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    body = json.loads(r.read().decode())
                if not body.get("ok"):
                    raise TelegramError(body.get("description", "unknown error"))
                return body["result"]
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    retry = json.loads(e.read().decode()).get("parameters", {}).get("retry_after", 2)
                    time.sleep(retry)
                    continue
                raise TelegramError(f"HTTP {e.code}: {e.read().decode()[:200]}") from e
            except urllib.error.URLError as e:
                if attempt == 2:
                    raise TelegramError(f"network: {e.reason}") from e
                time.sleep(2 * (attempt + 1))
        raise TelegramError("gave up after 3 attempts")

    def me(self) -> dict:
        return self._call("getMe")

    def resolve_to(self, to: str | None) -> tuple[str, int | None]:
        """A destination name from the book (TELEGRAM_TO_<NAME>) or a literal '<chat>' / '<chat>_<topic>'.
        Returns (chat_id, thread_id or None)."""
        if to is None or to == "":
            return self.resolve_chat(None), None
        val = str(to)
        if not val.lstrip("-").replace("_", "").isdigit():          # a name -> look it up
            key = val.lower()
            if key not in self.dests:
                raise TelegramError(f"unknown destination '{to}' in book '{self.book or '-'}': define TELEGRAM_TO_{key.upper()} "
                                    f"(known: {', '.join(sorted(self.dests)) or 'none'})")
            val = self.dests[key]
        chat, _, thread = val.partition("_")
        return chat, (int(thread) if thread else None)

    def resolve_chat(self, chat: str | None) -> str:
        """Chat by name (TELEGRAM_CHAT_<NAME>), numeric id, or None for the default chat."""
        if chat is None or chat == "" or str(chat).lower() == "default":
            if not self.default_chat:
                raise TelegramError(f"no default chat: set TELEGRAM_CHAT_ID in {self.name}.env")
            return self.default_chat
        c = str(chat)
        if c.lstrip("-").isdigit():
            return c
        key = c.lower()
        if key not in self.chats:
            raise TelegramError(f"unknown chat '{chat}': define TELEGRAM_CHAT_{key.upper()} in {self.name}.env "
                                f"(known: {', '.join(sorted(self.chats)) or 'none'})")
        return self.chats[key]

    def resolve_topic(self, topic: str | int | None, chat: str | None = None) -> int | None:
        """Topic by name or numeric id. Names are TELEGRAM_TOPIC_<TOPIC> for the default chat and
        TELEGRAM_TOPIC_<CHAT>_<TOPIC> for a named chat. None/general = no topic."""
        if topic is None or topic == "":
            return None
        if isinstance(topic, int) or str(topic).isdigit():
            return int(topic)
        key = str(topic).lower()
        if key in ("general", "none"):
            return None
        chat_key = (str(chat).lower() if chat and not str(chat).lstrip("-").isdigit() else "")
        candidates = [f"{chat_key}_{key}"] if chat_key and chat_key != "default" else [key]
        for cand in candidates:
            if cand in self.topics:
                return int(self.topics[cand])
        want = f"TELEGRAM_TOPIC_{candidates[0].upper()}"
        raise TelegramError(f"unknown topic '{topic}' for chat '{chat or 'default'}': define {want} in {self.name}.env "
                            f"(known: {', '.join(sorted(self.topics)) or 'none'})")

    def send(self, text: str, to: str | None = None, chat: str | None = None, topic: str | int | None = None,
             silent: bool = False, chat_id: str | None = None) -> list[int]:
        """Send text (plain, no parse_mode — so R multiples, underscores and * are safe).
        to: a destination name from the address book (preferred), or '<chat>_<topic>' literally.
        chat/topic: the older explicit form; chat_id is a legacy alias.
        Splits at 4096 chars on line boundaries. Returns message ids."""
        if to is not None:
            chat, thread = self.resolve_to(to)
        else:
            chat = chat or chat_id
            thread = self.resolve_topic(topic, chat)
            chat = self.resolve_chat(chat)
        ids = []
        for chunk in _chunks(text):
            res = self._call("sendMessage", chat_id=chat, text=chunk,
                             message_thread_id=thread,
                             disable_notification="true" if silent else None,
                             disable_web_page_preview="true")
            ids.append(res["message_id"])
        return ids

    def discover_topics(self) -> list[tuple[int, str, str]]:
        """(thread_id, chat_id, sample text) for topic messages seen by getUpdates.
        Post one line in each topic first; General messages carry no thread id."""
        seen = {}
        for upd in self._call("getUpdates", timeout=0):
            msg = upd.get("message") or upd.get("edited_message") or {}
            tid = msg.get("message_thread_id")
            if not tid:
                continue
            name = (msg.get("reply_to_message") or {}).get("forum_topic_created", {}).get("name")
            created = msg.get("forum_topic_created", {}).get("name")
            sample = created or name or (msg.get("text") or "")[:40]
            seen.setdefault(tid, (str(msg["chat"]["id"]), sample))
        return sorted((tid, c, s) for tid, (c, s) in seen.items())

    def discover_chats(self) -> list[tuple[str, str]]:
        """Chats that have messaged this bot recently (for finding a chat id)."""
        seen = {}
        for upd in self._call("getUpdates", timeout=0):
            msg = upd.get("message") or upd.get("channel_post") or upd.get("my_chat_member", {})
            chat = msg.get("chat") if isinstance(msg, dict) else None
            if chat:
                seen[str(chat["id"])] = chat.get("title") or chat.get("username") or chat.get("first_name", "")
        return sorted(seen.items())


def _chunks(text: str):
    while len(text) > MAX_LEN:
        cut = text.rfind("\n", 0, MAX_LEN)
        cut = cut if cut > 0 else MAX_LEN
        yield text[:cut]
        text = text[cut:].lstrip("\n")
    yield text


def send(text: str, to: str | None = None, book: str = "trading", bot: str = "rickyassist_bot", **kw) -> list[int]:
    """Convenience for runners: send(text, to="alerts")  (book 'trading', bot Ricky by default)."""
    return Bot(bot, book=book).send(text, to=to, **kw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bot", default="rickyassist_bot", help="name of <bot>.env under .config/telegram")
    ap.add_argument("--book", default="trading", help="address book <book>.env under .config/telegram (default trading)")
    ap.add_argument("--to", help="destination name from the book (TELEGRAM_TO_<NAME>) or literal <chat>_<topic>")
    ap.add_argument("--chat", help="chat name (TELEGRAM_CHAT_<NAME>) or numeric id; default TELEGRAM_CHAT_ID")
    ap.add_argument("--topic", help="topic name (TELEGRAM_TOPIC_<NAME>) or numeric thread id; default General")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--test", action="store_true", help="getMe + send a timestamped test line")
    g.add_argument("--discover", action="store_true", help="print chat ids that have messaged the bot")
    g.add_argument("--topics", action="store_true", help="print topic thread ids seen (post in each topic first)")
    g.add_argument("--send", metavar="TEXT")
    g.add_argument("--list", action="store_true", help="list configured bots")
    g.add_argument("--show", action="store_true", help="show the address book(s) and destinations")
    a = ap.parse_args(argv)

    try:
        if a.list:
            bots = list_bots()
            print(f"config dir: {CONFIG_DIR}")
            print("\n".join(bots) if bots else "(no *.env files)")
            return 0
        book_file = CONFIG_DIR / f"{a.book}.env"
        bot = Bot(a.bot, book=a.book if book_file.is_file() else None)
        if a.show:
            print(f"books in {CONFIG_DIR}: {', '.join(list_books()) or 'none'}")
            print(f"book '{a.book}': {'present' if book_file.is_file() else 'MISSING'}")
            for k, v in sorted(bot.dests.items()):
                print(f"  to {k:<20} {v}")
            if bot.default_chat:
                print(f"  bot default chat   {bot.default_chat}")
            return 0
        if a.discover:
            rows = bot.discover_chats()
            if not rows:
                print("no updates seen — send the bot a message (or post in the group) and run again")
            for cid, title in rows:
                print(f"{cid:>16}  {title}")
            return 0
        if a.topics:
            rows = bot.discover_topics()
            if not rows:
                print("no topic messages seen — post one line in each topic, then run again")
            print(f"{'thread_id':>10}  {'chat_id':>16}  topic / sample")
            for tid, cid, sample in rows:
                print(f"{tid:>10}  {cid:>16}  {sample}")
            print("\nput the ones you want in the env file as TELEGRAM_TOPIC_<NAME>=<thread_id>")
            return 0
        if a.test:
            me = bot.me()
            print(f"bot ok: @{me['username']} (id {me['id']})")
            stamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            where = f"{a.book}/{a.to}" if a.to else (f"chat {a.chat or 'default'} / topic {a.topic or 'General'}")
            ids = bot.send(f"PAPER · TEST · common.alerts.telegram\nbot @{me['username']} via {a.bot}.env → {where}\n{stamp}",
                           to=a.to, chat=a.chat, topic=a.topic)
            print(f"sent message id {ids[0]} to {where}")
            return 0
        if a.send:
            ids = bot.send(a.send, to=a.to, chat=a.chat, topic=a.topic)
            print(f"sent {ids}")
            return 0
        ap.print_help()
        return 2
    except TelegramError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
