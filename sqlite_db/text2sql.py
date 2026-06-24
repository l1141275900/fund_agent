import sqlite3
from env import BASE_DIR
import logging

logger = logging.getLogger("agent")

class Text2SqlClient:
    def __init__(self,db_dir = BASE_DIR / "funds.db"):
        if not db_dir.exists():
            raise FileNotFoundError(f"数据库文件 {db_dir} 不存在")

        # 连接数据库
        self.conn = sqlite3.connect(db_dir)
        self.conn.row_factory = sqlite3.Row     #让每行返回dict_like对象
        # 获取游标（用户告诉游标要执行什么SQL，游标去SQL里干活）
        self.cursor = self.conn.cursor()

    # 要暴露给llm
    def get_table_list(self):
        """
        获取指定表的数据库表结构
        """
        try:
            self.cursor.execute("PRAGMA table_list")
            tables = self.cursor.fetchall()
            return str([table[1] for table in tables if not table[1].startswith('sqlite_')])

        except sqlite3.Error as e:
            logger.error(f"获取表列表失败：{e}")
            return f"失败：{e}"

    # 要暴露给llm
    def get_schema(self, table_name: str):
        """
        获取指定表的数据库表结构
        """
        try:
            self.cursor.execute(f"PRAGMA table_info({table_name})")     #table_info()函数返回表的列信息，包括列名、数据类型、是否可空、默认值等信息
            columns = self.cursor.fetchall()
            return str(columns)
        except sqlite3.Error as e:
            logger.error(f"获取表结构失败：{e}")
            return f"失败：{e}"

    # 要暴露给llm
    def execute_sql_query(self, sql: str,limit:int = 100,offset:int = 0):
        """
        执行自定义SQL语句（查询）
        """
        if "SELECT" not in sql:
            return "禁止非查询语句，请重新生成sql并重试"
        if "LIMIT" in sql or "OFFSET" in sql:
            return "禁止 LIMIT与OFFSET 语句，请重新生成sql并重试"
        if limit > 1000:
            return "禁止LIMIT 超过 1000，请重新生成sql并重试"
        if offset < 0:
            return "禁止OFFSET 小于 0，请重新生成sql并重试"

        sql += f" LIMIT {limit} OFFSET {offset}"

        try:
            self.cursor.execute(sql)
            logger.info(f"执行SQL语句 {sql} 完成")
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"执行SQL语句 {sql} 失败：{e}")
            return f"失败：{e}"

    # 要暴露给llm
    def execute_sql_modify(self, sql: str):
        """
        执行自定义SQL语句（更新、插入、删除）
        """
        if "DROP" in sql or "ALTER" in sql or ("DELETE" in sql and "WHERE" not in sql) or ("UPDATE" in sql and "WHERE" not in sql):
            return "禁止 DROP、ALTER、不带 WHERE 的 DELETE/UPDATE，请重新生成sql并重试"
        try:
            self.cursor.execute(sql)
            self.conn.commit()
            logger.info(f"执行SQL语句 {sql} 完成")
            return "success"
        except sqlite3.Error as e:
            logger.error(f"执行SQL语句 {sql} 失败：{e}")
            return f"失败：{e}"