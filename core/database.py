import sqlite3
from datetime import datetime
from pathlib import Path
from .config import DB_FILE, TIMEZONE

def _connect():
    conn = sqlite3.connect(str(DB_FILE), check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def add_message(channel, user_id, role, content):
    conn = _connect()
    conn.execute(
        "INSERT INTO messages(channel,user_id,role,content,created_at) VALUES(?,?,?,?,?)",
        (channel, str(user_id), role, content, datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    conn.close()

def get_history(channel, user_id, limit=8):
    conn = _connect()
    rows = conn.execute(
        """SELECT role, content FROM messages
           WHERE channel=? AND user_id=?
           ORDER BY id DESC LIMIT ?""",
        (channel, str(user_id), limit)
    ).fetchall()
    conn.close()
    return list(reversed([{"role": r, "content": c} for r, c in rows]))


def clear_messages(channel, user_id):
    """Delete all messages for a given channel/user pair."""
    conn = _connect()
    conn.execute(
        "DELETE FROM messages WHERE channel=? AND user_id=?",
        (channel, str(user_id))
    )
    conn.commit()
    conn.close()

def log_activity(channel, user_id, action, status, detail=""):
    conn = _connect()
    conn.execute(
        "INSERT INTO activity_log(channel,user_id,action,status,detail,created_at) VALUES(?,?,?,?,?,?)",
        (channel, str(user_id), action, status, detail[:4000],
         datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    conn.close()

def recent_activity(limit=30):
    conn = _connect()
    rows = conn.execute(
        """SELECT channel,user_id,action,status,detail,created_at
           FROM activity_log ORDER BY id DESC LIMIT ?""", (limit,)
    ).fetchall()
    conn.close()
    return rows
