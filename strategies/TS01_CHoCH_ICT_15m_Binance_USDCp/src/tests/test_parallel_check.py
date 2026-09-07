"""bin/parallel-check (v1.28): the watcher-vs-TS01 comparison during the parallel run.
State files only — nothing detected, sent or written."""
import importlib.util
import json
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def pc():
    spec = importlib.util.spec_from_loader(
        "parallel_check",
        importlib.machinery.SourceFileLoader("parallel_check", str(REPO / "bin" / "parallel-check")))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _write(p: Path, keys) -> Path:
    p.write_text(json.dumps({k: True for k in keys}), encoding="utf-8")
    return p


def test_setups_reads_announced_keys_and_ignores_lifecycle_subkeys(pc, tmp_path):
    now = int(time.time() * 1000)
    f = _write(tmp_path / "s.json", [
        f"LINKUSDC:{now}",                    # an announced setup
        f"LINKUSDC:fill:{now}",               # lifecycle subkey — not a setup
        f"LINKUSDC:{now}:nostop:1234",        # guard subkey
        f"1000PEPEUSDC:{now - 900000}",       # digits in the symbol are fine
        "_last_heartbeat", "_seeded_from",    # bookkeeping
    ])
    got = pc.setups(f)
    assert set(got) == {("LINKUSDC", now), ("1000PEPEUSDC", now - 900000)}


def test_setups_is_quiet_about_a_missing_or_broken_file(pc, tmp_path, capsys):
    assert pc.setups(tmp_path / "nope.json") == {}
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert pc.setups(tmp_path / "bad.json") == {}


def test_unfunded_watcher_setups_are_not_reported_as_divergence(pc, tmp_path, monkeypatch, capsys):
    now = int(time.time() * 1000)
    shared, funded_only, unfunded = now - 3600_000, now - 7200_000, now - 10800_000
    watcher = _write(tmp_path / "w.json", [f"LINKUSDC:{shared}", f"ETHUSDC:{funded_only}",
                                           f"SUIUSDC:{unfunded}"])
    ts01 = _write(tmp_path / "t.json", [f"LINKUSDC:{shared}", f"SOLUSDC:{now - 1800_000}"])
    monkeypatch.setattr(pc, "TS01", ts01)
    monkeypatch.setattr(pc, "funded", lambda: {"LINKUSDC": 0.5, "ETHUSDC": 0.5, "SOLUSDC": 1.0,
                                               "SUIUSDC": 0.0})
    assert pc.main(["--days", "7", "--watcher-state", str(watcher)]) == 0
    out = capsys.readouterr().out
    assert "both agree:        1" in out
    assert "watcher only:      1" in out and "ETHUSDC" in out       # funded → needs explaining
    assert "TS01 only:         1" in out and "SOLUSDC" in out
    assert "watcher, unfunded: 1" in out and "SUIUSDC" not in out.split("-- watcher only --")[1]


def test_setups_outside_the_window_are_excluded(pc, tmp_path, monkeypatch, capsys):
    now = int(time.time() * 1000)
    old = now - 30 * 86400_000
    watcher = _write(tmp_path / "w.json", [f"LINKUSDC:{old}"])
    monkeypatch.setattr(pc, "TS01", _write(tmp_path / "t.json", [f"LINKUSDC:{old}"]))
    monkeypatch.setattr(pc, "funded", lambda: {"LINKUSDC": 0.5})
    pc.main(["--days", "7", "--watcher-state", str(watcher)])
    out = capsys.readouterr().out
    assert "both agree:        0" in out and "No divergence" in out


def _log(tmp_path, iso):
    d = tmp_path / "logs"
    d.mkdir(exist_ok=True)
    (d / "TS01-runner.jsonl").write_text(json.dumps({"ts": iso, "event": "cycle"}) + "\n",
                                         encoding="utf-8")
    return d.parent


def test_inherited_setups_are_excluded_from_agreement(pc, tmp_path, monkeypatch, capsys):
    """TS01's state was seeded from the watcher's, so agreement on pre-first-cycle setups
    is inheritance, not detection. Counting it as evidence would fake the parallel run."""
    import datetime as dt
    now = int(time.time() * 1000)
    start = now - 48 * 3600_000
    monkeypatch.setattr(pc, "STRAT", _log(tmp_path, dt.datetime.fromtimestamp(
        start / 1000, dt.timezone.utc).isoformat(timespec="seconds")))
    old, new = now - 96 * 3600_000, now - 3600_000
    watcher = _write(tmp_path / "w.json", [f"LINKUSDC:{old}", f"SOLUSDC:{new}"])
    ts01 = tmp_path / "t.json"
    ts01.write_text(json.dumps({f"LINKUSDC:{old}": True, f"SOLUSDC:{new}": True,
                                "_seeded_from": r"C:\Users\Admin\.choch-watch\state.json"}),
                    encoding="utf-8")
    monkeypatch.setattr(pc, "TS01", ts01)
    monkeypatch.setattr(pc, "funded", lambda: {"LINKUSDC": 0.5, "SOLUSDC": 1.0})
    pc.main(["--days", "7", "--watcher-state", str(watcher)])
    out = capsys.readouterr().out
    assert "excluded 1 inherited setup" in out
    assert "both agree:        1" in out          # only the setup after the first cycle counts


def test_include_inherited_says_plainly_that_it_is_not_evidence(pc, tmp_path, monkeypatch, capsys):
    now = int(time.time() * 1000)
    old = now - 96 * 3600_000
    watcher = _write(tmp_path / "w.json", [f"LINKUSDC:{old}"])
    ts01 = tmp_path / "t.json"
    ts01.write_text(json.dumps({f"LINKUSDC:{old}": True, "_seeded_from": "x"}), encoding="utf-8")
    monkeypatch.setattr(pc, "TS01", ts01)
    monkeypatch.setattr(pc, "funded", lambda: {"LINKUSDC": 0.5})
    pc.main(["--days", "7", "--watcher-state", str(watcher), "--include-inherited"])
    out = capsys.readouterr().out
    assert "not evidence of independent detection" in out and "both agree:        1" in out


def test_after_overrides_the_log_derived_cutoff(pc, tmp_path, monkeypatch, capsys):
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    ms = lambda h: int((now - dt.timedelta(hours=h)).timestamp() * 1000)  # noqa: E731
    monkeypatch.setattr(pc, "STRAT", _log(tmp_path, (now - dt.timedelta(hours=96)).isoformat()))
    watcher = _write(tmp_path / "w.json", [f"LINKUSDC:{ms(50)}", f"SOLUSDC:{ms(2)}"])
    monkeypatch.setattr(pc, "TS01", _write(tmp_path / "t.json",
                                           [f"LINKUSDC:{ms(50)}", f"SOLUSDC:{ms(2)}"]))
    monkeypatch.setattr(pc, "funded", lambda: {"LINKUSDC": 0.5, "SOLUSDC": 1.0})
    after = (now - dt.timedelta(hours=24)).replace(tzinfo=None).isoformat(timespec="seconds")
    pc.main(["--days", "7", "--watcher-state", str(watcher), "--after", after])
    out = capsys.readouterr().out
    assert "(--after)" in out and "both agree:        1" in out
