"""
对话历史持久化模块。

采用 SQLite 单文件数据库（路径由 env.py 的 sqlite_db_dir 指定），
包含两张表：
  chat_sessions  — 会话目录（标题、时间）
  chat_messages  — 每条消息（角色、内容、时间）

设计要点：
  - 懒连接：首次 SQL 操作时才 connect，避免构造时卡顿
  - 写操作自动创建 session：save_* 方法会先 ensure_session
  - 读操作不自动创建：get_* 仅查询，无副作用
"""
import sqlite3
import logging
from datetime import datetime
from env import sqlite_db_dir

logger = logging.getLogger("agent")


class ChatHistoryClient:
    """
    SQLite 对话历史客户端。

    用法:
        client = ChatHistoryClient()
        client.create_tables()          # 首次使用前建表（幂等）
        client.save_user_message(sid, "你好")
        client.save_assistant_message(sid, "你好！有什么可以帮你的？")
        sessions = client.get_sessions()
        messages = client.get_messages(sid)
        client.close()
    """

    def __init__(self, db_dir: str = str(sqlite_db_dir)):
        """
        db_dir: SQLite 数据库文件路径。
                默认使用 env.py 中配置的 sqlite_db_dir。
                支持通过参数覆盖（如 Text2Sql 传入临时 db 路径）。
        """
        self.db_dir = db_dir
        # conn/cursor 初始为 None，首次访问时才连接（懒加载）
        # 这样 ChatHistoryClient() 构造开销为零，适合被短生命周期调用
        self.conn = None
        self.cursor = None

    def _ensure_connection(self):
        """
        确保 conn 和 cursor 可用。

        三步：
          1. 若 conn 已存在 → 用 SELECT 1 探测连接是否有效
          2. 若失效（如跨线程、已 close）→ 重置为 None
          3. 若为 None → sqlite3.connect 建新连接

        sqlite3.Row 作为 row_factory 的好处：
          cursor.fetchone() 返回 sqlite3.Row 对象，
          它支持 dict(row) 转换和 row['column'] 键访问。
          对比默认的 tuple 返回，可读性更高。
        """
        try:
            if self.conn is not None:
                # 心跳探测：轻量查询验证连接未断开
                self.conn.execute("SELECT 1")
        except (sqlite3.ProgrammingError, AttributeError):
            # 跨线程使用或连接已关闭 → 重置
            self.conn = None
            self.cursor = None

        if self.conn is None:
            # 建立新连接
            # check_same_thread=False：允许跨线程使用。
            # ChatHistoryClient 每个实例仅在单线程内顺序使用，不存在并发写风险。
            self.conn = sqlite3.connect(self.db_dir, check_same_thread=False)
            # row_factory 决定 fetch 结果的格式：sqlite3.Row 可像 dict 一样访问
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()

        return self.conn, self.cursor

    def create_tables(self):
        """
        建表（幂等 — IF NOT EXISTS 保证重复执行不报错）。

        chat_sessions 表:
          session_id TEXT PK  — UUID 主键，前端 localStorage 生成
          title       TEXT    — 对话标题，默认"新对话"
          created_at  TEXT    — ISO 时间戳
          updated_at  TEXT    — 每次新消息时更新，用于排序侧边栏列表

        chat_messages 表:
          id          INTEGER PK  — 自增主键（本地 db，无需对外暴露）
          session_id  TEXT FK     — 关联 chat_sessions
          role        TEXT        — "user" 或 "assistant"
          content     TEXT        — 消息全文
          created_at  TEXT        — ISO 时间戳
        """
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
        """
        确保 chat_sessions 中存在该 session 行。

        使用 INSERT OR IGNORE：
          若 session_id 已存在 → 不插入（保留原 title 和 created_at）
          若不存在 → 插入新行

        对比 INSERT OR REPLACE：后者会 DELETE + INSERT，丢失原 title。
        """
        conn, cursor = self._ensure_connection()
        now = datetime.now().isoformat()          # ISO 8601 格式，如 "2026-07-01T13:00:00"
        cursor.execute(
            "INSERT OR IGNORE INTO chat_sessions (session_id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (session_id, "新对话", now, now),
        )
        conn.commit()

    def save_user_message(self, session_id: str, content: str):
        """
        保存用户消息。

        自动完成：
          1. ensure_session  — 首次对话创建会话行
          2. INSERT 消息     — 写入 chat_messages
          3. UPDATE 标题     — 若标题仍是"新对话"，用第一条用户消息的前 40 字做标题
          4. UPDATE 时间     — 更新 updated_at，使该会话在列表中排在前面
        """
        conn, cursor = self._ensure_connection()
        self._ensure_session(session_id)
        now = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO chat_messages (session_id, role, content, created_at) VALUES (?,?,?,?)",
            (session_id, "user", content, now),
        )
        # 首次用户消息 → 自动生成标题（仅当标题仍是默认值时）
        cursor.execute(
            "UPDATE chat_sessions SET title=?, updated_at=? WHERE session_id=? AND title='新对话'",
            (content[:40], now, session_id),
        )
        # 无论是否首次，都刷新 updated_at（用于侧边栏排序）
        cursor.execute(
            "UPDATE chat_sessions SET updated_at=? WHERE session_id=?",
            (now, session_id),
        )
        conn.commit()

    def save_assistant_message(self, session_id: str, content: str):
        """
        保存 AI 回复消息。
        同样更新 updated_at 以维持按最近活动排序。
        """
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
        """
        获取所有会话列表（排除 daily_focus 内部会话）。

        按 updated_at 降序 → 最近活跃的对话在最上面。
        返回 list[dict]，每个 dict 包含 session_id, title, updated_at。
        """
        conn, cursor = self._ensure_connection()
        cursor.execute(
            "SELECT session_id, title, updated_at FROM chat_sessions "
            "WHERE session_id != 'daily_focus' "
            "ORDER BY updated_at DESC"
        )
        # cursor.fetchall() 返回 list[sqlite3.Row]
        # dict(row) 将 Row 转为普通 dict（便于 JSON 序列化返回给前端）
        return [dict(row) for row in cursor.fetchall()]

    def get_messages(self, session_id: str) -> list[dict]:
        """
        获取指定会话的所有消息。

        按 created_at 升序 → 时间顺序对话流。
        返回 list[dict]，每个 dict 包含 role, content, created_at。

        注意：不调用 _ensure_session —— 若 session 不存在则返回空列表，无副作用。
        """
        conn, cursor = self._ensure_connection()
        cursor.execute(
            "SELECT role, content, created_at FROM chat_messages WHERE session_id=? ORDER BY created_at ASC",
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def delete_session(self, session_id: str):
        """
        删除会话及其所有消息（已考虑外键约束的删除顺序）。

        先删 messages 再删 session，兼容未启用 PRAGMA foreign_keys 的情况。
        """
        conn, cursor = self._ensure_connection()
        cursor.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
        cursor.execute("DELETE FROM chat_sessions WHERE session_id=?", (session_id,))
        conn.commit()

    def close(self):
        """
        关闭数据库连接。
        cursor 和 conn 分别关闭后置 None，防止 _ensure_connection 复用已关闭的句柄。
        """
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        self.conn = None
        self.cursor = None
