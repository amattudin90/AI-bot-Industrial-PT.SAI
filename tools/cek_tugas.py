"""Diagnosa lokasi tugas pada Google Sheet TASK_SHEET_ID.

Jalankan dari folder mana pun: python tools/cek_tugas.py [kata-kunci]
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KEYWORD = " ".join(sys.argv[1:]).strip() or "layout new building"
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar.events",
]


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    sheet_id = os.environ.get("TASK_SHEET_ID", "").strip()
    token_file = PROJECT_ROOT / "token.json"
    if not sheet_id:
        raise SystemExit("TASK_SHEET_ID kosong di .env")
    if not token_file.is_file():
        raise SystemExit("token.json tidak ditemukan. Jalankan: python tools/generate_token.py")

    credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    sheets = build("sheets", "v4", credentials=credentials)
    meta = sheets.spreadsheets().get(spreadsheetId=sheet_id).execute()
    print(f"TASK_SHEET_ID: {sheet_id[:6]}...{sheet_id[-6:]}")
    print(f"Nama file Google: {meta['properties']['title']}\n{'-' * 60}")

    found = False
    for sheet in meta["sheets"]:
        title = sheet["properties"]["title"]
        values = sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"'{title}'"
        ).execute().get("values", [])
        print(f"Tab '{title}': data terisi sampai baris {len(values)}")
        for row_number, row in enumerate(values, start=1):
            if any(KEYWORD.lower() in str(cell).lower() for cell in row):
                found = True
                print(f"  DITEMUKAN di '{title}', baris {row_number}: {row[:8]}")
    if not found:
        print(f"Kata kunci '{KEYWORD}' tidak ditemukan pada file ini.")


if __name__ == "__main__":
    main()
