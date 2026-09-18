import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_allowed = os.getenv("TELEGRAM_ALLOWED_USERS", "").strip()
TELEGRAM_ALLOWED_USERS = {
    int(x.strip()) for x in _allowed.split(",") if x.strip().isdigit()
}

V1_FILE = os.getenv("V1_FILE", "Capa analysis machine per procesV1.xlsx")
V2_FILE = os.getenv("V2_FILE", "Capa analysis machine per procesV2.xlsx")

DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "").strip()
SHEET_ID = os.getenv("SHEET_ID", "").strip()
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "client_secret.json")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
GOOGLE_SHEET_RANGE = os.getenv("GOOGLE_SHEET_RANGE", "Sheet1!A:D")

MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "50"))
DB_FILE = Path(os.getenv("DB_FILE", DATA_DIR / "factory_ai.db"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Jakarta")

SYSTEM_NAME = "Factory AI Operations System"
APP_VERSION = "V10 Unified"
