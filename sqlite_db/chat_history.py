import sqlite3
import logging
from datetime import datetime
from env import sqlite_db_dir

logger = logging.getLogger("agent")


class ChatHistoryClient:
    def __init__(self, db_dir: str = str(sqlite_db_dir)):
        self.db_dir = db_dir
        self.conn = None
        self.cursor = None

    def _ensure_connection(self):
        try:
            if self.conn is not None:
                self.conn.execute("SELECT 1")
        except (sqlite3.ProgrammingError, AttributeError):
            self.conn = None
            self.cursor = None
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_dir)
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()
        return self.conn, self.cursor

    def create_tables(self):
        conn, cursor = self._ensure_connection()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT DEFAULT '新对话',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
            )
        """)
        conn.commit()
        logger.info("chat_history 表创建完成")

    def _ensure_session(self, session_id: str):
        conn, cursor = self._ensure_connection()
        now = datetime.now().isoformat()
        cursor.execute(
            "INSERT OR IGNORE INTO chat_sessions (session_id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (session_id, "新对话", now, now),
        )
        conn.commit()

    def save_user_message(self, session_id: str, content: str):
        conn, cursor = self._ensure_connection()
        self._ensure_session(session_id)
        now = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO chat_messages (session_id, role, content, created_at) VALUES (?,?,?,?)",
            (session_id, "user", content, now),
        )
        # 用第一条用户消息作为对话标题
        cursor.execute(
            "UPDATE chat_sessions SET title=?, updated_at=? WHERE session_id=? AND title='新对话'",
            (content[:40], now, session_id),
        )
        cursor.execute(
            "UPDATE chat_sessions SET updated_at=? WHERE session_id=?",
            (now, session_id),
        )
        conn.commit()

    def save_assistant_message(self, session_id: str, content: str):
        conn, cursor = self._ensure_connection()
        self._ensure_session(session_id)
        now = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO chat_messages (session_id, role, content, created_at) VALUES (?,?,?,?)",
            (session_id, "assistant", content, now),
        )
        cursor.execute(
            "UPDATE chat_sessions SET updated_at=? WHERE session_id=?",
            (now, session_id),
        )
        conn.commit()

    def get_sessions(self) -> list[dict]:
        conn, cursor = self._ensure_connection()
        cursor.execute(
            "SELECT session_id, title, updated_at FROM chat_sessions WHERE session_id != 'daily_focus' ORDER BY updated_at DESC"
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_messages(self, session_id: str) -> list[dict]:
        conn, cursor = self._ensure_connection()
        cursor.execute(
            "SELECT role, content, created_at FROM chat_messages WHERE session_id=? ORDER BY created_at ASC",
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def delete_session(self, session_id: str):
        conn, cursor = self._ensure_connection()
        cursor.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
        cursor.execute("DELETE FROM chat_sessions WHERE session_id=?", (session_id,))
        conn.commit()

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        self.conn = None
        self.cursor = None
