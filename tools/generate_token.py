"""Create/refresh the Google OAuth token for this project."""
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLIENT_SECRET_FILE = PROJECT_ROOT / "client_secret.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar.events",
]


def main() -> None:
    if not CLIENT_SECRET_FILE.is_file():
        raise SystemExit(
            "File client_secret.json tidak ditemukan. Letakkan kredensial OAuth Google "
            "milikmu di folder utama Factory AI terlebih dahulu."
        )
    print("Memulai autentikasi Google. Browser akan segera terbuka.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
    credentials = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
    print(f"Token Google berhasil disimpan: {TOKEN_FILE.name}")


if __name__ == "__main__":
    main()
