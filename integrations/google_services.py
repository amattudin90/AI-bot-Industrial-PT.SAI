import io
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from core.config import (
    GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE, DRIVE_FOLDER_ID,
    SHEET_ID, GOOGLE_SHEET_RANGE, TIMEZONE
)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar.events",
]

def get_google_services():
    creds = None
    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return (
        build("drive", "v3", credentials=creds),
        build("sheets", "v4", credentials=creds),
        build("calendar", "v3", credentials=creds),
    )

def save_text_to_drive(drive_service, text, filename):
    if not DRIVE_FOLDER_ID:
        raise RuntimeError("DRIVE_FOLDER_ID belum diisi.")
    metadata = {
        "name": filename,
        "parents": [DRIVE_FOLDER_ID],
        "mimeType": "text/plain",
    }
    media = MediaIoBaseUpload(io.BytesIO(text.encode("utf-8")), mimetype="text/plain", resumable=False)
    result = drive_service.files().create(body=metadata, media_body=media, fields="id,webViewLink").execute()
    return result.get("id"), result.get("webViewLink")

def append_sheet(sheets_service, values):
    if not SHEET_ID:
        raise RuntimeError("SHEET_ID belum diisi.")
    return sheets_service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=GOOGLE_SHEET_RANGE,
        valueInputOption="USER_ENTERED",
        body={"values": [values]},
    ).execute()

def create_calendar_event(calendar_service, data):
    event = {
        "summary": data["summary"],
        "description": data["description"],
        "start": {"dateTime": data["start_time"], "timeZone": TIMEZONE},
        "end": {"dateTime": data["end_time"], "timeZone": TIMEZONE},
    }
    return calendar_service.events().insert(calendarId="primary", body=event).execute()
