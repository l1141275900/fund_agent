import sqlite3
import logging
import asyncio
from env import sqlite_db_dir

logger = logging.getLogger("agent")
class FundCollectionClient:
    def __init__(self,db_dir:str=sqlite_db_dir):
        # # 连接数据库，若数据库文件不存在，则创建
        # self.conn = sqlite3.connect(db_dir)
        # self.conn.row_factory = sqlite3.Row     #让每行返回dict_like对象
        # # 获取游标（用户告诉游标要执行什么SQL，游标去SQL里干活）
        self.conn = None
        self.cursor = None
        self.db_dir = db_dir
    def _ensure_connection(self):
        """确保当前线程有连接（每个线程独立创建）"""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_dir)
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()
        return self.conn, self.cursor

    def create_funds_db(self):
        """
        创建基金数据库表
        """
        conn, cursor = self._ensure_connection()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS funds (
            code        TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            fund_type   TEXT,
            manager     TEXT,
            company     TEXT,
            scale       REAL,
            fee_rate    REAL,
            created_at  TEXT
        )
        """)    #REAL表示float类型
        """
        SQLite 的类型系统比较宽松——你写 `TEXT` 的列存数字也不会报错。但写好类型声明是给读代码的人看的，表示你的意图。
        """
        conn.commit()  #在游标执行完SQL后，需要提交事务，才能将数据写入数据库文件
        logger.info("基金数据库表创建完成")
        return "success"

    def insert_funds(self,data:list)->str:
        """
        批量插入基金数据
        """
        conn, cursor = self._ensure_connection()
        cursor.executemany(
            "INSERT OR IGNORE INTO funds (code,name,fund_type,manager,company,scale,fee_rate,created_at) VALUES (?,?,?,?,?,?,?,?)",
            data
        )
        # 普通 `INSERT` 在主键重复时抛异常。`INSERT OR IGNORE` 在主键重复时静默跳过，非常适合"可能重复拉取数据"的场景——不会因重复插入而崩溃。
        conn.commit()  #在游标执行完SQL后，需要使用连接对象提交事务，才能将数据写入数据库文件
        logger.info(f"基金数据 {data} 插入完成")
        return f"基金数据 {data} 插入完成"

    def query_funds_by_code(self,code):
        """
        根据基金代码查询基金数据
        """
        conn, cursor = self._ensure_connection()
        cursor.execute("SELECT * FROM funds WHERE code = ?",(code,))
        return cursor.fetchone()

    def query_all_funds(self):
        """
        查询所有基金数据
        """
        conn, cursor = self._ensure_connection()
        cursor.execute("SELECT * FROM funds")
        return cursor.fetchall()

    def query_funds_by_one_attr(self,attr:str,value:str):
        """
        根据基金属性查询基金数据
        """
        conn, cursor = self._ensure_connection()
        cursor.execute(f"SELECT * FROM funds WHERE {attr} LIKE ?", ("%" + value + "%",))
        # ("%"+value+"%")表示模糊查询，%表示任意字符
        # fetchall()表示查询所有结果，fetchone()表示查询第一个结果
        return cursor.fetchall()

    def update_funds(self,code,data:dict):
        """
        更新基金数据
        """
        conn, cursor = self._ensure_connection()
        fields = {k:v for k,v in data.items() if v is not None}  # 过滤掉None值
        if not fields:
            logger.info(f"基金数据 {code} 更新失败：{data} 无更新字段")
            return f"基金数据 {code} 更新失败：{data} 无更新字段"

        try:
            # 构建更新语句
            update_sql = f"UPDATE funds SET {', '.join([f'{k}=?' for k in fields.keys()])} WHERE code=?"
            cursor.execute(update_sql, tuple(fields.values()) + (code,))
            conn.commit()
            logger.info(f"基金数据 {code} 更新完成")
            return f"基金数据 {code} 更新完成"
        except sqlite3.Error as e:
            logger.error(f"基金数据 {code} 更新失败：{e}")
            return f"基金数据 {code} 更新失败：{e}"


    def delete_funds(self,code):
        """
        删除基金数据
        """
        conn, cursor = self._ensure_connection()
        try:
            cursor.execute("DELETE FROM funds WHERE code = ?", (code,))
            conn.commit()
            logger.info(f"基金数据 {code} 删除完成")
            return f"基金数据 {code} 删除完成"
        except sqlite3.Error as e:
            logger.error(f"基金数据 {code} 删除失败：{e}")
            return f"基金数据 {code} 删除失败：{e}"

    def close(self):
        """
        关闭数据库连接
        """
        conn, cursor = self._ensure_connection()
        cursor.close()
        logger.info("数据库连接已关闭")
        return "success"


async def main():
    pass

if __name__ == '__main__':
    asyncio.run(main())
