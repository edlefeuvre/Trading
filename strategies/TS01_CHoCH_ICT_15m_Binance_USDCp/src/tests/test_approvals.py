"""The Approvals buttons and the 'approved' reply, with the bot and the weekly runner faked.

A press from anyone but Ed is refused; Apply/Hold call `weekly --apply/--hold --proposal <id>`;
Re-run calls `weekly --run-now`; a typed 'approved' reply to the approval message maps to the id
in that message; the message is edited with the outcome and keeps its buttons on failure.
Also: the Sunday folder naming and the index page."""
import datetime as dt

from common.alerts import approvals
from common.reports import weekly_folder as wf


class FakeBot:
    name, book = "rickyassist_bot", "trading"

    def __init__(self):
        self.answers, self.edits = [], []

    def answer_callback(self, cid, text="", alert=False):
        self.answers.append((cid, text, alert))

    def edit(self, chat_id, message_id, text, html=False, buttons=None):
        self.edits.append((chat_id, message_id, text, buttons))


APPROVAL_TEXT = ("PAPER · APPROVAL · TS01 · R factors 06 Sep 2026\nETHUSDC 0.5 → 1  · positive both\n"
                 "Applies to config/universe.yaml only. Expires Sun 13 Sep 06:00 UTC.\nid deadbeef1234 · reply 'approved' or 'hold' also works")


def cb(data, uid=111, text=APPROVAL_TEXT):
    return {"callback_query": {"id": "q1", "data": data, "from": {"id": uid},
                               "message": {"chat": {"id": -100}, "message_id": 42, "text": text}}}


def reply(text, uid=111):
    return {"message": {"text": text, "from": {"id": uid},
                        "reply_to_message": {"chat": {"id": -100}, "message_id": 42, "text": APPROVAL_TEXT}}}


def make(monkeypatch, code=0, out="APPLIED: ETHUSDC 0.5→1 · TS01 v1.26 · commit abc1234"):
    bot = FakeBot()
    calls = []
    monkeypatch.setattr(approvals, "owner_id", lambda b: "111")

    def runner(ts, args, repo):
        calls.append((ts, args)); return code, out
    return bot, calls, runner


def test_non_owner_is_refused(monkeypatch, tmp_path):
    bot, calls, runner = make(monkeypatch)
    r = approvals.handle_update(cb("ts01:apply:deadbeef1234", uid=999), tmp_path, bot=bot, runner=runner)
    assert r["result"].startswith("refused") and calls == [] and bot.answers[0][2] is True
    r = approvals.handle_update(reply("approved", uid=999), tmp_path, bot=bot, runner=runner)
    assert r["result"].startswith("refused") and calls == []


def test_apply_button_runs_weekly_apply_and_edits(monkeypatch, tmp_path):
    bot, calls, runner = make(monkeypatch)
    r = approvals.handle_update(cb("ts01:apply:deadbeef1234"), tmp_path, bot=bot, runner=runner)
    assert calls == [("ts01", ["--apply", "--proposal", "deadbeef1234"])]
    assert r["code"] == 0 and bot.answers[0][1] == "Applying…"
    chat, mid, text, buttons = bot.edits[0]
    assert (chat, mid) == (-100, 42) and text.startswith(APPROVAL_TEXT) and "APPLIED" in text and buttons is None


def test_hold_and_rerun(monkeypatch, tmp_path):
    bot, calls, runner = make(monkeypatch, out="HELD: deadbeef1234")
    approvals.handle_update(cb("ts01:hold:deadbeef1234"), tmp_path, bot=bot, runner=runner)
    approvals.handle_update(cb("ts01:rerun"), tmp_path, bot=bot, runner=runner)
    assert calls == [("ts01", ["--hold", "--proposal", "deadbeef1234"]), ("ts01", ["--run-now"])]
    assert len(bot.edits) == 1                       # re-run does not rewrite the old message


def test_failed_apply_keeps_buttons(monkeypatch, tmp_path):
    bot, calls, runner = make(monkeypatch, code=1, out="NOT APPLIED: proposal expired")
    approvals.handle_update(cb("ts01:apply:deadbeef1234"), tmp_path, bot=bot, runner=runner)
    _, _, text, buttons = bot.edits[0]
    assert "NOT APPLIED" in text and buttons and buttons[0][0][1] == "ts01:apply:deadbeef1234"


def test_text_reply_maps_to_the_message_id(monkeypatch, tmp_path):
    bot, calls, runner = make(monkeypatch)
    approvals.handle_update(reply("approved"), tmp_path, bot=bot, runner=runner)
    approvals.handle_update(reply("hold"), tmp_path, bot=bot, runner=runner)
    approvals.handle_update(reply("approved 00000000aaaa"), tmp_path, bot=bot, runner=runner)
    assert [a for _, a in calls] == [["--apply", "--proposal", "deadbeef1234"], ["--hold", "--proposal", "deadbeef1234"],
                                     ["--apply", "--proposal", "00000000aaaa"]]


def test_unrelated_updates_ignored(monkeypatch, tmp_path):
    bot, calls, runner = make(monkeypatch)
    assert not approvals.handle_update({"message": {"text": "hello", "from": {"id": 111}}}, tmp_path, bot=bot, runner=runner)["handled"]
    assert not approvals.handle_update(cb("other:thing"), tmp_path, bot=bot, runner=runner)["handled"]
    assert calls == []


# ---- the Sunday folder --------------------------------------------------------------------------
def test_week_folder_name():
    assert wf.week_folder_name(dt.date(2026, 9, 6)) == "2026-09-06 W36"     # a Sunday maps to itself
    assert wf.week_folder_name(dt.date(2026, 9, 2)) == "2026-09-06 W36"     # a Wednesday maps to its Sunday
    assert wf.week_folder_name(dt.date(2026, 9, 7)) == "2026-09-13 W37"
    assert wf.week_folder_name(dt.date(2027, 1, 1)) == "2027-01-03 W53"     # ISO week 53 of 2026


def test_render_index_lists_each_file_once():
    filed = wf.Filed(folder={"id": "f", "url": "https://drive/f"}, items=[
        wf.Item("01 - TS01 weekly R-factor review.md", "x", as_doc=True, line="the review", url="u1", doc_url="d1"),
        wf.Item("01 - TS01 weekly r_factors.csv", b"x", line="data", url="u2"),
        wf.Item("03 - study-hours.html", b"x", line="study", url="u3")], errors=["05 - x.csv: boom"])
    md = wf.render_index(dt.date(2026, 9, 6), filed, ["filing rule"], ["ETH 0.5 → 1"], generated_by="test")
    assert md.startswith("# Sunday review — 6 September 2026 (W36)")
    assert md.count("01 - TS01 weekly R-factor review") == 1 and "](d1)" in md    # Doc link preferred
    assert "## Decisions taken" in md and "## Open for decision" in md and "boom" in md
    assert not any(l.startswith("|") for l in md.splitlines())
