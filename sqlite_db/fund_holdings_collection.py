import sqlite3
from env import BASE_DIR
import logging

logger = logging.getLogger("agent")

class FundHoldingsCollectionClient:
    def __init__(self,db_dir:str = BASE_DIR / "funds.db"):
        # 连接数据库，若数据库文件不存在，则创建
        self.conn = sqlite3.connect(db_dir)
        self.conn.row_factory = sqlite3.Row     #让每行返回dict_like对象
        # 获取游标（用户告诉游标要执行什么SQL，游标去SQL里干活）
        self.cursor = self.conn.cursor()

    def create_fund_holdings_db(self):
        """
        创建持仓数据库表
        """
        self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS fund_holdings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code   TEXT NOT NULL,       -- 基金代码
            stock_code  TEXT NOT NULL,       -- 持仓股票代码
            stock_name  TEXT,                -- 股票名称
            ratio       REAL,                -- 占净值比例（%）
            report_date TEXT,                -- 报告期，如 "2026Q1"
            UNIQUE(fund_code, stock_code, report_date)
        """)
        self.conn.commit()
        logger.info("持仓表创建完成")
        return "success"

    def close(self):
        """
        关闭数据库连接
        """
        self.conn.close()
