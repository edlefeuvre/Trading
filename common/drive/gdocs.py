r"""common.drive.gdocs — Google Docs in Drive, as Ed, for the per-setup trade reports.

Why OAuth as the user and not a service account: service accounts have no Drive storage
quota and cannot own files in a normal My Drive folder — writing into a folder merely
shared with one fails with storageQuotaExceeded. Authenticating as Ed means the files land
in his existing folder, he owns them, and he can edit them on the phone like any Doc.

Credentials, following the same convention as binance/ and telegram/:
    %USERPROFILE%\.config\google\oauth-client.json   the downloaded Desktop OAuth client
    %USERPROFILE%\.config\google\token.json          written by --authorise, refreshed here

Scope is drive.file ONLY: this app can touch files it created and nothing else in Drive.

One-time, on the machine that will run the jobs (opens a browser):
    python -m common.drive.gdocs --authorise

Then:
    python -m common.drive.gdocs --test <folder_id>     # create, read back, update, report the link
    python -m common.drive.gdocs --whoami

The report lifecycle keeps Ed's own notes: everything below NOTES_MARKER is read back from
the live Doc and carried into the next write, so a runner update never destroys what he
typed on the phone.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("TRADING_CONFIG_DIR", Path.home() / ".config")) / "google"
CLIENT_FILE = CONFIG_DIR / "oauth-client.json"
TOKEN_FILE = CONFIG_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DOC_MIME = "application/vnd.google-apps.document"
NOTES_MARKER = "## My notes"


class DriveError(RuntimeError):
    pass


def _deps():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload
    except ImportError as e:
        raise DriveError(
            "missing packages — run:  python -m pip install --upgrade "
            "google-api-python-client google-auth-oauthlib"
        ) from e
    return Request, Credentials, InstalledAppFlow, build, MediaIoBaseUpload


def authorise(force: bool = False) -> str:
    """One-time browser consent. Writes token.json. Returns the account email."""
    Request, Credentials, InstalledAppFlow, build, _ = _deps()
    if not CLIENT_FILE.is_file():
        raise DriveError(f"{CLIENT_FILE} not found — download the Desktop OAuth client JSON there")
    if TOKEN_FILE.is_file() and not force:
        print(f"{TOKEN_FILE} already exists; use --authorise --force to replace it")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:  # noqa: BLE001 — Windows ACLs differ; not fatal
        pass
    if not creds.refresh_token:
        print("WARNING: no refresh token was issued. The consent screen is probably in "
              "'Testing' status, or consent was previously granted. Re-run with --force.")
    return _email(creds)


def _email(creds) -> str:
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r).get("email", "(unknown)")
    except Exception:  # noqa: BLE001 — drive.file scope may not include userinfo
        return "(email not visible under the drive.file scope)"


def _creds():
    Request, Credentials, _, _, _ = _deps()
    if not TOKEN_FILE.is_file():
        raise DriveError(f"{TOKEN_FILE} not found — run:  python -m common.drive.gdocs --authorise")
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise DriveError("stored token cannot be refreshed — run --authorise --force. If this "
                             "recurs weekly, the OAuth consent screen is in 'Testing' status, which "
                             "expires refresh tokens after 7 days; set it Internal or publish it.")
    return creds


class Client:
    def __init__(self):
        _, _, _, build, MediaIoBaseUpload = _deps()
        self._media = MediaIoBaseUpload
        self.svc = build("drive", "v3", credentials=_creds(), cache_discovery=False)

    # ---- read -------------------------------------------------------------
    def find(self, name: str, folder_id: str | None = None) -> dict | None:
        """A file this app created, by exact name. drive.file scope sees only our own files."""
        q = [f"name = '{name}'", "trashed = false"]
        if folder_id:
            q.append(f"'{folder_id}' in parents")
        r = self.svc.files().list(q=" and ".join(q), spaces="drive", pageSize=5,
                                  fields="files(id,name,webViewLink,modifiedTime)").execute()
        f = r.get("files", [])
        return f[0] if f else None

    def export_md(self, file_id: str) -> str:
        try:
            return self.svc.files().export(fileId=file_id, mimeType="text/markdown").execute().decode("utf-8")
        except Exception:  # noqa: BLE001 — older docs or an export hiccup
            return self.svc.files().export(fileId=file_id, mimeType="text/plain").execute().decode("utf-8")

    def notes_of(self, file_id: str) -> str:
        """Whatever Ed has written below the marker, so a rewrite never destroys it."""
        try:
            body = self.export_md(file_id)
        except Exception:  # noqa: BLE001
            return ""
        i = body.find(NOTES_MARKER)
        if i < 0:
            return ""
        # Docs' markdown export escapes punctuation ("\--test"). It round-trips at one level
        # rather than accumulating, but strip it so the text stays clean over months of updates.
        return re.sub(r"\\([-_*#\[\]()`>+.!~|%$&])", r"\1", body[i + len(NOTES_MARKER):]).strip()

    # ---- write ------------------------------------------------------------
    def _media_body(self, markdown: str):
        return self._media(io.BytesIO(markdown.encode("utf-8")), mimetype="text/markdown", resumable=False)

    def create(self, name: str, markdown: str, folder_id: str) -> dict:
        meta = {"name": name, "mimeType": DOC_MIME, "parents": [folder_id]}
        return self.svc.files().create(body=meta, media_body=self._media_body(markdown),
                                       fields="id,name,webViewLink").execute()

    def update(self, file_id: str, markdown: str) -> dict:
        return self.svc.files().update(fileId=file_id, media_body=self._media_body(markdown),
                                       fields="id,name,webViewLink").execute()

    def upsert(self, name: str, markdown: str, folder_id: str, file_id: str | None = None,
               keep_notes: bool = True) -> dict:
        """Create or update, preserving Ed's notes section. The file id and URL never change,
        so a link posted to Telegram at SETUP still resolves after the close."""
        if file_id is None:
            found = self.find(name, folder_id)
            file_id = found["id"] if found else None
        if file_id is None:
            return self.create(name, markdown, folder_id)
        if keep_notes:
            notes = self.notes_of(file_id)
            if notes:
                head = markdown.split(NOTES_MARKER)[0].rstrip()
                markdown = f"{head}\n\n{NOTES_MARKER}\n\n{notes}\n"
        return self.update(file_id, markdown)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--authorise", action="store_true", help="one-time browser consent")
    g.add_argument("--whoami", action="store_true")
    g.add_argument("--test", metavar="FOLDER_ID", help="create, read back and update a scratch doc")
    ap.add_argument("--force", action="store_true", help="with --authorise, replace an existing token")
    a = ap.parse_args(argv)
    try:
        if a.authorise:
            print(f"authorised as {authorise(a.force)}")
            print(f"token stored at {TOKEN_FILE}")
            return 0
        if a.whoami:
            print(_email(_creds()))
            return 0
        c = Client()
        name = "TS01 drive test - safe to delete"
        r = c.upsert(name, "# TS01 Drive test\n\nCreated by `--test`. Safe to delete.\n\n"
                           f"{NOTES_MARKER}\n\nType something here, then run --test again.\n", a.test)
        print(f"created/updated: {r['name']}\n{r['webViewLink']}")
        notes = c.notes_of(r["id"])
        print(f"notes read back ({len(notes)} chars): {notes[:120]!r}")
        r2 = c.upsert(name, "# TS01 Drive test\n\nSecond write — the link and id must be unchanged.\n\n"
                            f"{NOTES_MARKER}\n\n(this default is replaced by whatever you typed)\n",
                      a.test, file_id=r["id"])
        print(f"same id after update: {r2['id'] == r['id']}  ({r2['webViewLink']})")
        return 0
    except DriveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
