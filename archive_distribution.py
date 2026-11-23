import os
import sys
import json
import subprocess
import gspread
from datetime import date, timedelta
from google.oauth2.credentials import Credentials as UserCredentials
from google.auth.transport.requests import AuthorizedSession, Request
from google.auth.exceptions import RefreshError
from google_auth_oauthlib.flow import InstalledAppFlow
from config import load_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")
DISTRIBUTION_PATH = os.path.join(BASE_DIR, "distribution.json")
OAUTH_CLIENT_SECRET_PATH = os.path.join(BASE_DIR, "oauth_client_secret.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.json")

SPREADSHEET_ID = load_config()["spreadsheet_id"]
ARCHIVE_FOLDER_NAME = "Archivo Finanzas"

EXPENSES_SHEET = "Gastos del Mes"
INCOMES_SHEET = "Ingresos del Mes"
RESERVES_SHEET = "Reservas del Mes"

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DRIVE_OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive"]

DRIVE_API = "https://www.googleapis.com/drive/v3"


def _drive_session():
    # Uses your own Google identity (not the service account) so new files/folders
    # are owned by your Drive quota instead of the service account's (which is 0).
    creds = None
    if os.path.exists(TOKEN_PATH):
        try:
            creds = UserCredentials.from_authorized_user_file(TOKEN_PATH, DRIVE_OAUTH_SCOPES)
        except (ValueError, json.JSONDecodeError):
            creds = None  # unreadable/corrupt token file — fall through to a fresh consent

    if creds and creds.valid:
        return AuthorizedSession(creds)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            # Refresh token revoked or expired (Testing-mode apps expire it after 7
            # days), so a cached token from last month is dead. Just re-consent.
            creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CLIENT_SECRET_PATH, DRIVE_OAUTH_SCOPES)
        creds = flow.run_local_server(port=0)

    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())
    return AuthorizedSession(creds)


def _find_or_create_folder(session, name):
    r = session.get(f"{DRIVE_API}/files", params={
        "q": f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false and 'me' in owners",
        "fields": "files(id)",
    })
    r.raise_for_status()
    files = r.json().get("files", [])
    if files:
        return files[0]["id"]
    r = session.post(f"{DRIVE_API}/files", json={
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    })
    r.raise_for_status()
    folder_id = r.json()["id"]
    print(f"  Created '{name}' folder in your Drive")
    return folder_id


def _copy_file(session, file_id, archive_name, folder_id):
    r = session.post(f"{DRIVE_API}/files/{file_id}/copy", json={
        "name": archive_name,
        "parents": [folder_id],
    })
    r.raise_for_status()


def _clear_data_rows(ws):
    rows = ws.get_all_values()
    if len(rows) > 1:
        ws.batch_clear([f"A2:Z{len(rows)}"])


def _delete_non_monthly_reserves(ws):
    rows = ws.get_all_values()
    to_delete = []
    for i, row in enumerate(rows[1:], start=2):  # 1-indexed, skip header
        tags = row[1] if len(row) > 1 else ""
        if "mensual" not in tags:
            to_delete.append(i)
    for row_idx in reversed(to_delete):
        ws.delete_rows(row_idx)
    return len(to_delete)


def _latest_date_with_day(today, day):
    """Most recent date <= today whose day-of-month is `day` (months lacking that day are skipped)."""
    if not 1 <= day <= 31:
        raise ValueError(day)
    year, month = today.year, today.month
    for _ in range(12):
        try:
            candidate = date(year, month, day)
        except ValueError:
            candidate = None
        if candidate and candidate <= today:
            return candidate
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    raise ValueError(day)


def main():
    if len(sys.argv) != 2:
        print("Usage: python archive_distribution.py DAY")
        print("  DAY: day of month the new distribution starts on; resolves to the latest date")
        print("       with that day number that is not in the future (e.g. 29 on Oct 4 -> Sep 29)")
        sys.exit(1)

    try:
        new_start = _latest_date_with_day(date.today(), int(sys.argv[1]))
    except ValueError:
        print(f"Invalid day: {sys.argv[1]}. Pass a day number between 1 and 31.")
        sys.exit(1)

    last_day = new_start - timedelta(days=1)
    archive_name = f"{last_day.month}-{last_day.year}"

    # Step 1: copy the full spreadsheet into the archive folder (in your own Drive)
    print(f"Copying 'Finanzas' to '{ARCHIVE_FOLDER_NAME}/{archive_name}'...")
    session = _drive_session()
    folder_id = _find_or_create_folder(session, ARCHIVE_FOLDER_NAME)
    _copy_file(session, SPREADSHEET_ID, archive_name, folder_id)
    print("  Done.")

    # Step 2: reset the active spreadsheet
    gc = gspread.service_account(filename=CREDENTIALS_PATH, scopes=SHEETS_SCOPES)
    ss = gc.open_by_key(SPREADSHEET_ID)

    print("Clearing Gastos del Mes...")
    _clear_data_rows(ss.worksheet(EXPENSES_SHEET))

    print("Clearing Ingresos del Mes...")
    _clear_data_rows(ss.worksheet(INCOMES_SHEET))

    print("Removing non-monthly reserves from Reservas del Mes...")
    n = _delete_non_monthly_reserves(ss.worksheet(RESERVES_SHEET))
    print(f"  Removed {n} non-monthly reserve(s).")

    # Step 3: save the new distribution start
    with open(DISTRIBUTION_PATH, "w") as f:
        json.dump({"start": str(new_start)}, f)
    print(f"Distribution start set to {new_start}.")

    # Step 4: populate the new distribution
    print("\nFetching transactions for the new distribution...")
    subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "get_daily_transactions.py")],
        check=True,
    )


if __name__ == "__main__":
    main()
