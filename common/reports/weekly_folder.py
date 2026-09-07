r"""common.reports.weekly_folder — one Google Drive folder per Sunday review.

Ed's filing rule (6 Sep 2026): everything examined at a given Sunday review lives in ONE folder,
    <Weeklies>/yyyy-mm-dd Wnn/          e.g.  Trading/Weeklies/2026-09-06 W36/
numbered in reading order so there is one place to go through all the reports:
    00 - Sunday review yyyy-mm-dd Wnn — index     (Doc, generated last)
    01 - TS01 weekly R-factor review              (Doc + .md + r_factors.csv)
    02 - ...                                      (whatever else was studied that week)
    03 - study-hours.html, 04 - paper-track.csv, 05 - tranche-setups.csv

This module knows the folder convention and the index. It does not know the strategy; callers hand
it (name, bytes/markdown, kind) items. Drive access is common.drive.files; everything here is
fail-soft at the call site — a filing failure is a WARN in the Digest message, never a job failure.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from common.drive.files import Drive, DriveError

MIME = {".md": "text/markdown", ".csv": "text/csv", ".html": "text/html", ".json": "application/json",
        ".txt": "text/plain", ".yaml": "text/plain"}


def sunday_of(d: dt.date) -> dt.date:
    """The Sunday that closes the ISO week containing d (a Sunday maps to itself)."""
    return d + dt.timedelta(days=(6 - d.weekday()))


def week_folder_name(d: dt.date, pattern: str = "{sunday:%Y-%m-%d} W{iso_week:02d}") -> str:
    s = sunday_of(d)
    return pattern.format(sunday=s, iso_week=s.isocalendar()[1])


@dataclass
class Item:
    name: str                 # file name inside the week folder, e.g. "01 - TS01 weekly R-factor review.md"
    data: bytes | str         # content
    as_doc: bool = False      # also/only as a converted Google Doc (name without extension)
    line: str = ""            # one line for the index
    url: str = ""             # filled after upload
    doc_url: str = ""


@dataclass
class Filed:
    folder: dict
    items: list[Item] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def file_week(drive: Drive, weeklies_id: str, day: dt.date, items: list[Item],
              pattern: str = "{sunday:%Y-%m-%d} W{iso_week:02d}") -> Filed:
    """Ensure the week folder and upsert every item. Never raises for a single item; collects errors."""
    folder = drive.ensure_folder(week_folder_name(day, pattern), weeklies_id)
    out = Filed(folder=folder)
    for it in items:
        try:
            ext = "." + it.name.rsplit(".", 1)[-1] if "." in it.name else ""
            if ext in MIME:
                r = drive.upsert_file(it.name, folder["id"], it.data, MIME[ext])
                it.url = r["url"]
            if it.as_doc:
                text = it.data.decode("utf-8") if isinstance(it.data, bytes) else it.data
                doc_name = it.name[: -len(ext)] if ext else it.name
                r = drive.upsert_doc(doc_name, folder["id"], text)
                it.doc_url = r["url"]
        except DriveError as e:
            out.errors.append(f"{it.name}: {e}")
        out.items.append(it)
    return out


def render_index(day: dt.date, filed: Filed, decisions: list[str], open_items: list[str],
                 pattern: str = "{sunday:%Y-%m-%d} W{iso_week:02d}", generated_by: str = "") -> str:
    """Markdown for `00 - … index`. Bulleted label lines only (Drive renders pipe tables badly)."""
    s = sunday_of(day)
    title = week_folder_name(day, pattern)
    lines = [f"# Sunday review — {s.day} {s:%B %Y} ({title.split()[-1]})", "",
             "One folder per Sunday. Everything examined at the review sits here, numbered in the order to read it.", "",
             "## In this folder", ""]
    seen = set()
    for it in filed.items:
        stem = it.name.rsplit(".", 1)[0]
        if stem in seen:
            continue
        seen.add(stem)
        link = it.doc_url or it.url
        label = f"[{stem}]({link})" if link else f"**{stem}**"
        lines.append(f"- {label}" + (f" — {it.line}" if it.line else ""))
    if decisions:
        lines += ["", "## Decisions taken", ""] + [f"{i}. {d}" for i, d in enumerate(decisions, 1)]
    if open_items:
        lines += ["", "## Open for decision", ""] + [f"{i}. {d}" for i, d in enumerate(open_items, 1)]
    if filed.errors:
        lines += ["", "## Filing warnings", ""] + [f"- {e}" for e in filed.errors]
    lines += ["", f"_Generated {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M UTC}"
              + (f" by {generated_by}" if generated_by else "") + ". Research, not advice._"]
    return "\n".join(lines) + "\n"
