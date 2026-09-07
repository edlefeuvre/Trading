"""The Sunday programme's proposal → apply / hold path, on a throwaway git repo.

Covers: the review layout (Status line, sections, no pipe table outside a code block), the
proposal record, and `--apply` refusing an expired proposal or a changed params.yaml, applying
all-or-nothing (only the listed symbols change, exactly one change-log row, version bumped,
one commit), leaving universe.yaml byte-identical on a mid-way failure, `--hold`, and a second
apply being a no-op. Telegram and Drive are never touched."""
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src import weekly

STRAT = Path(weekly.__file__).resolve().parent.parent

ROWS = [
    dict(symbol="SOLUSDC", dataset_start="2024-01", dataset_end="2026-09-05", bars=90000, n_trades=74, n_12m=27,
         r_prior=0.219, r_12m=0.226, tier_now=1.0, tier_proposed=1.0, provisional=True, rule="positive both"),
    dict(symbol="ETHUSDC", dataset_start="2024-01", dataset_end="2026-09-05", bars=90000, n_trades=116, n_12m=49,
         r_prior=0.243, r_12m=0.053, tier_now=0.5, tier_proposed=1.0, provisional=False, rule="positive both"),
    dict(symbol="LTCUSDC", dataset_start="2024-01", dataset_end="2026-09-05", bars=90000, n_trades=95, n_12m=39,
         r_prior=-0.217, r_12m=0.459, tier_now=0.5, tier_proposed=0.5, provisional=False, rule="positive one"),
    dict(symbol="AAVEUSDC", dataset_start="2024-01", dataset_end="2026-09-05", bars=90000, n_trades=42, n_12m=34,
         r_prior=0.414, r_12m=-0.367, tier_now=0.5, tier_proposed=0.5, provisional=False, rule="positive one"),
    dict(symbol="BNBUSDC", dataset_start="2024-01", dataset_end="2026-09-05", bars=90000, n_trades=89, n_12m=30,
         r_prior=-0.117, r_12m=-0.127, tier_now=0.0, tier_proposed=0.0, provisional=False, rule="positive neither"),
]
CHANGES = [("ETHUSDC", 0.5, 1.0)]
NOW = dt.datetime(2026, 9, 6, 6, 0, tzinfo=dt.timezone.utc)
META = dict(now=NOW, k=5, book=356.0, cap=20.0, spec_version="1.25", params_hash="abc123")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git repo shaped like the real one: strategies/<slug>/{config,STRATEGY.md,results}."""
    root = tmp_path / "Trading"
    here = root / "strategies" / STRAT.name
    shutil.copytree(STRAT / "config", here / "config")
    (here / "STRATEGY.md").write_text(
        "---\nid: TS01\nversion: 1.25\nmode: PAPER\n---\n\n# TS01\n\n## Change log\n\n"
        "| Date | Version | Section | Change | Files |\n|---|---|---|---|---|\n"
        "| 2026-09-06 | 1.25 | §6 | previous | `x` |\n", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "book.yaml").write_text("book_usd: 356\ndrive:\n  enabled: false\n", encoding="utf-8")
    git(root, "init", "-q"); git(root, "config", "user.email", "t@t"); git(root, "config", "user.name", "t")
    git(root, "add", "-A"); git(root, "commit", "-qm", "base")
    monkeypatch.setattr(weekly, "HERE", here)
    monkeypatch.setattr(weekly, "REPO", root)
    monkeypatch.setattr(weekly, "edit_approval_message", lambda *a, **k: None)
    return root, here


def write_proposal(here, expires=None, phash=None, changes=None, status="proposed"):
    out = here / "results" / "weekly" / "2026-09-06"
    out.mkdir(parents=True, exist_ok=True)
    ph = phash or weekly.params_hash(here / "config" / "params.yaml")
    prop = dict(id="deadbeef1234", run="2026-09-06", spec_version="1.25", params_hash=ph,
                changes=changes or [dict(symbol="ETHUSDC", **{"from": 0.5, "to": 1.0}, rule="positive both")],
                book_usd=356, status=status, expires=expires or "2099-01-01T00:00:00Z", approval_message=None)
    (out / "proposal.json").write_text(json.dumps(prop), encoding="utf-8")
    digest = weekly.digest_text(ROWS, CHANGES, META, 30)
    (out / "summary.md").write_text(weekly.render_summary(ROWS, CHANGES, META, 30, "PROPOSED", [], [], digest, prop["id"]),
                                    encoding="utf-8")
    return out / "proposal.json"


class A:
    def __init__(self, **kw):
        self.apply = kw.get("apply", False); self.hold = kw.get("hold", False); self.proposal = kw.get("proposal")


# ---- the review document --------------------------------------------------------------------
def test_summary_layout_and_status_line():
    digest = weekly.digest_text(ROWS, CHANGES, META, 30)
    md = weekly.render_summary(ROWS, CHANGES, META, 30, "PROPOSED — 1 change(s) awaiting Ed", [], ["item one"], digest, "deadbeef1234")
    order = [md.index(h) for h in ("- **Status:**", "## Summary", "For the Sunday pass", "## Detail", "## Original message")]
    assert order == sorted(order), "sections in reading order: header, summary, detail, original"
    assert "ETHUSDC 0.5 → 1" in md and "**ETHUSDC 0.5 → 1** (positive both)" in md
    assert "1 improving" in md and "1 deteriorating" in md          # LTC improving, AAVE deteriorating
    assert "LTC" in md.split("improving")[1].split(")")[0] and "AAVE" in md.split("deteriorating")[1].split(")")[0]
    # no pipe table outside a fenced block (Drive renders them badly)
    outside = "".join(part for i, part in enumerate(md.split("```")) if i % 2 == 0)
    assert not any(line.startswith("|") for line in outside.splitlines())
    assert "<-- CHANGE" in md and md.count("PAPER · WEEKLY · TS01") >= 2
    md2 = weekly.set_status_line(md, "APPLIED 2026-09-06")
    assert md2.count("- **Status:** APPLIED 2026-09-06") == 1 and "PROPOSED —" not in md2


def test_digest_unchanged_shape():
    d = weekly.digest_text(ROWS, CHANGES, META, 30)
    assert d.splitlines()[0] == "PAPER · WEEKLY · TS01"
    assert "ETHUSDC" in d and "<-- CHANGE" in d and "1 proposed change(s): ETHUSDC 0.5→1" in d
    import re
    assert re.search(r"^SOLUSDC\s+74\s+27\*", d, re.M)                  # provisional star kept


# ---- apply / hold -----------------------------------------------------------------------------
def test_apply_rewrites_only_listed_symbols_and_commits(repo):
    root, here = repo
    pfile = write_proposal(here)
    before = (here / "config" / "universe.yaml").read_text(encoding="utf-8")
    assert weekly.apply(A(apply=True)) == 0
    after = (here / "config" / "universe.yaml").read_text(encoding="utf-8")
    changed = [l for l in after.splitlines() if l not in before.splitlines()]
    assert len(changed) == 1 and "ETHUSDC" in changed[0] and "tier: 1," in changed[0], changed
    doc = (here / "STRATEGY.md").read_text(encoding="utf-8")
    assert "version: 1.26" in doc and doc.count("| 2026-") == 2 and "proposal deadbeef1234" in doc
    prop = json.loads(pfile.read_text())
    assert prop["status"] == "applied" and prop["version"] == "1.26" and prop["commit_subject"].startswith("TS01 v1.26: apply")
    assert git(root, "log", "--oneline").count("\n") == 1                 # exactly one new commit
    assert git(root, "status", "--porcelain") == ""                      # everything it touched is committed
    assert git(root, "log", "-1", "--format=%s") == prop["commit_subject"]
    assert "APPLIED 2026-" in (pfile.parent / "summary.md").read_text(encoding="utf-8")
    assert (here / "results" / "coverage.csv").read_text().count("ETHUSDC") == 1
    # second apply is a no-op
    assert weekly.apply(A(apply=True)) == 0
    assert git(root, "log", "--oneline").count("\n") == 1


def test_apply_refuses_expired_and_changed_params(repo, capsys):
    root, here = repo
    write_proposal(here, expires="2026-09-01T00:00:00Z")
    assert weekly.apply(A(apply=True)) == 1 and "expired" in capsys.readouterr().out
    write_proposal(here, phash="0000000000000000")
    assert weekly.apply(A(apply=True)) == 1 and "params.yaml changed" in capsys.readouterr().out
    assert git(root, "log", "--oneline").count("\n") == 0


def test_apply_failure_leaves_universe_untouched(repo, capsys):
    root, here = repo
    write_proposal(here, changes=[dict(symbol="ETHUSDC", **{"from": 0.5, "to": 1.0}, rule="positive both"),
                                  dict(symbol="NOPEUSDC", **{"from": 0.5, "to": 1.0}, rule="positive both")])
    before = (here / "config" / "universe.yaml").read_bytes()
    doc_before = (here / "STRATEGY.md").read_text(encoding="utf-8")
    assert weekly.apply(A(apply=True)) == 1
    assert "NOT APPLIED" in capsys.readouterr().out
    assert (here / "config" / "universe.yaml").read_bytes() == before
    assert (here / "STRATEGY.md").read_text(encoding="utf-8") == doc_before
    assert not (here / "config" / "universe.yaml.new").exists()
    assert git(root, "status", "--porcelain") == "" or "results" in git(root, "status", "--porcelain")


def test_apply_refuses_dirty_universe(repo, capsys):
    root, here = repo
    write_proposal(here)
    (here / "config" / "universe.yaml").write_text((here / "config" / "universe.yaml").read_text() + "# edit\n")
    assert weekly.apply(A(apply=True)) == 1 and "uncommitted" in capsys.readouterr().out


def test_hold_marks_and_changes_nothing(repo):
    root, here = repo
    pfile = write_proposal(here)
    before = (here / "config" / "universe.yaml").read_bytes()
    assert weekly.apply(A(hold=True)) == 0
    assert json.loads(pfile.read_text())["status"] == "held"
    assert (here / "config" / "universe.yaml").read_bytes() == before
    assert "HELD" in (pfile.parent / "summary.md").read_text(encoding="utf-8")
    assert git(root, "log", "--oneline").count("\n") == 0


def test_proposal_lookup_by_id_and_latest(repo):
    root, here = repo
    write_proposal(here)
    older = here / "results" / "weekly" / "2026-08-30"; older.mkdir(parents=True)
    (older / "proposal.json").write_text(json.dumps(dict(id="00000000aaaa", run="2026-08-30")))
    assert weekly.latest_proposal(None)[1]["id"] == "deadbeef1234"
    assert weekly.latest_proposal("00000000aaaa")[1]["run"] == "2026-08-30"
    assert weekly.latest_proposal("nope") == (None, None)
