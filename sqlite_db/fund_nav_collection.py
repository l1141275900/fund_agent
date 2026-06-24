import sqlite3
from env import BASE_DIR
import logging

logger = logging.getLogger("agent")

class FundNavCollectionClient:
    def __init__(self,db_dir:str = BASE_DIR / "funds.db"):
        # 连接数据库，若数据库文件不存在，则创建
        self.conn = sqlite3.connect(db_dir)
        self.conn.row_factory = sqlite3.Row     #让每行返回dict_like对象
        # 获取游标（用户告诉游标要执行什么SQL，游标去SQL里干活）
        self.cursor = self.conn.cursor()

    def create_fund_nav_db(self):
        """
        创建净值历史数据库表
        """
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS fund_nav (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code   TEXT NOT NULL,
            nav_date    TEXT NOT NULL,
            unit_nav    REAL,
            acc_nav     REAL,
            daily_pct   REAL,
            UNIQUE(fund_code, nav_date)
        );
        """)
        self.conn.commit()
        logger.info("净值历史表创建完成")
        return "success"

    def insert_fund_nav(self,data:dict):
        """
        插入净值历史数据
        """
        self.cursor.execute("""
        INSERT INTO fund_nav (fund_code, nav_date, unit_nav, acc_nav, daily_pct)
        VALUES (?, ?, ?, ?, ?)
        """,(data["fund_code"],data["nav_date"],data["unit_nav"],data["acc_nav"],data["daily_pct"]))
        self.conn.commit()
        logger.info(f"净值历史数据 {data} 插入完成")
        return f"净值历史数据 {data} 插入完成"

    def query_all_fund_nav(self):
        """
        查询所有净值历史数据
        """
        self.cursor.execute("""
        SELECT * FROM fund_nav
        """)
        return self.cursor.fetchall()

    def close(self):
        """
        关闭数据库连接
        """
        self.conn.close()
