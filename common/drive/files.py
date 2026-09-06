r"""common.drive.files — folders and files in Ed's Google Drive, as Ed.

Same credential as the per-setup trade reports (common/drive/gdocs.py, v1.21): OAuth as Ed,
scope `drive.file` only, refresh token at %USERPROFILE%\.config\google\token.json, written once by
`python -m common.drive.gdocs --authorise`. This module only sees files the app itself created.
No new consent, no new secret.

What it adds, for the Sunday programme (STRATEGY.md §8a) and any other report writer:
    ensure_folder(name, parent_id)            find-or-create a child folder by exact name
    upsert_file(name, parent_id, data, mime)  create, or update in place if a file of that name exists
    upsert_doc(name, parent_id, markdown)     same, converting Markdown → Google Doc (phones cannot
                                              preview .md; a Doc opens everywhere)
Every method returns {"id", "name", "url"}. Failures raise DriveError; callers are expected to be
fail-soft (a report that cannot be filed is a WARN, never a reason to skip the job).

    python -m common.drive.files --ls <folder_id>
    python -m common.drive.files --put README.md --into <folder_id> [--as-doc]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

from common.drive import gdocs
from common.drive.gdocs import DriveError  # noqa: F401  (one error type for the whole drive package)

FOLDER = "application/vnd.google-apps.folder"
GDOC = gdocs.DOC_MIME


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


class Drive:
    """Folders and files, on the same token as gdocs.Client (common/drive/gdocs.py --authorise)."""

    def __init__(self, token_path: Path | str | None = None):
        # token_path is accepted for tests; production always uses gdocs.TOKEN_FILE
        if token_path:
            gdocs.TOKEN_FILE = Path(token_path)
        self._svc = None

    @property
    def svc(self):
        if self._svc is None:
            _, _, _, build, _ = gdocs._deps()
            self._svc = build("drive", "v3", credentials=gdocs._creds(), cache_discovery=False)
        return self._svc

    def _files(self):
        return self.svc.files()

    @staticmethod
    def _url(f: dict) -> str:
        if f.get("mimeType") == GDOC:
            return f"https://docs.google.com/document/d/{f['id']}/edit"
        if f.get("mimeType") == FOLDER:
            return f"https://drive.google.com/drive/folders/{f['id']}"
        return f"https://drive.google.com/file/d/{f['id']}/view"

    def _out(self, f: dict) -> dict:
        return {"id": f["id"], "name": f.get("name"), "url": self._url(f), "mimeType": f.get("mimeType")}

    # ---- queries -------------------------------------------------------------------
    def find(self, name: str, parent_id: str, mime: str | None = None) -> dict | None:
        q = f"name = '{_q(name)}' and '{_q(parent_id)}' in parents and trashed = false"
        if mime:
            q += f" and mimeType = '{mime}'"
        try:
            res = self._files().list(q=q, fields="files(id,name,mimeType)", pageSize=5,
                                     supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        except Exception as e:  # noqa: BLE001
            raise DriveError(f"list failed: {e}") from e
        files = res.get("files", [])
        return self._out(files[0]) if files else None

    def ls(self, parent_id: str) -> list[dict]:
        try:
            res = self._files().list(q=f"'{_q(parent_id)}' in parents and trashed = false",
                                     fields="files(id,name,mimeType)", orderBy="name", pageSize=200,
                                     supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        except Exception as e:  # noqa: BLE001
            raise DriveError(f"list failed: {e}") from e
        return [self._out(f) for f in res.get("files", [])]

    # ---- writes --------------------------------------------------------------------
    def ensure_folder(self, name: str, parent_id: str) -> dict:
        found = self.find(name, parent_id, FOLDER)
        if found:
            return found
        try:
            f = self._files().create(body={"name": name, "mimeType": FOLDER, "parents": [parent_id]},
                                     fields="id,name,mimeType", supportsAllDrives=True).execute()
        except Exception as e:  # noqa: BLE001
            raise DriveError(f"create folder '{name}' failed: {e}") from e
        return self._out(f)

    def _upsert(self, name: str, parent_id: str, data: bytes, src_mime: str, target_mime: str | None) -> dict:
        _, _, _, _, MediaIoBaseUpload = gdocs._deps()
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=src_mime, resumable=False)
        existing = self.find(name, parent_id, target_mime)
        try:
            if existing:
                f = self._files().update(fileId=existing["id"], media_body=media,
                                         fields="id,name,mimeType", supportsAllDrives=True).execute()
            else:
                body = {"name": name, "parents": [parent_id]}
                if target_mime:
                    body["mimeType"] = target_mime
                f = self._files().create(body=body, media_body=media,
                                         fields="id,name,mimeType", supportsAllDrives=True).execute()
        except Exception as e:  # noqa: BLE001
            raise DriveError(f"upload '{name}' failed: {e}") from e
        return self._out(f)

    def upsert_file(self, name: str, parent_id: str, data: bytes | str, mime: str = "text/plain") -> dict:
        """A plain file kept as-is (.md, .csv, .html, .json). Updated in place if the name exists."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        return self._upsert(name, parent_id, data, mime, None)

    def upsert_doc(self, name: str, parent_id: str, markdown: str) -> dict:
        """Markdown → Google Doc (Drive converts on import). Updated in place if the name exists."""
        return self._upsert(name, parent_id, markdown.encode("utf-8"), "text/markdown", GDOC)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--token", default=None, help=f"token path (default {gdocs.TOKEN_FILE})")
    ap.add_argument("--ls", metavar="FOLDER_ID")
    ap.add_argument("--put", metavar="PATH")
    ap.add_argument("--into", metavar="FOLDER_ID")
    ap.add_argument("--as-doc", action="store_true", help="convert the Markdown to a Google Doc")
    ap.add_argument("--mkdir", metavar="NAME", help="ensure a child folder NAME under --into")
    a = ap.parse_args(argv)
    d = Drive(a.token)
    try:
        if a.ls:
            for f in d.ls(a.ls):
                print(f"{f['id']}  {f['mimeType'].split('.')[-1]:<10} {f['name']}")
            return 0
        if a.mkdir and a.into:
            print(json.dumps(d.ensure_folder(a.mkdir, a.into), indent=1)); return 0
        if a.put and a.into:
            p = Path(a.put)
            text = p.read_text(encoding="utf-8")
            r = d.upsert_doc(p.stem, a.into, text) if a.as_doc else \
                d.upsert_file(p.name, a.into, text, "text/markdown" if p.suffix == ".md" else "text/plain")
            print(json.dumps(r, indent=1)); return 0
    except DriveError as e:
        print(f"ERROR: {e}", file=sys.stderr); return 1
    ap.print_help(); return 2


if __name__ == "__main__":
    sys.exit(main())
