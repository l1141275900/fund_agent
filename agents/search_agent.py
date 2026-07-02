import os
from datetime import datetime
from tavily import TavilyClient
from agents.tools import Tool
from agents.agent_classes.base_agent import BaseAgent

import logging
import json
import httpx

from env import BASE_DIR
from sqlite_db.text2sql import Text2SqlClient
import akshare_func.main as akshare_func

logger = logging.getLogger("SearchAgent")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
class SearchAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.tavily_client = TavilyClient(TAVILY_API_KEY)
        self.platform_list = self._load_platforms()

    @property
    def agent_name(self) -> str:
        return "SearchAgent"

    @property
    def tools(self) -> list[Tool]:
        return [
            Tool(
                name="search",
                description="搜索互联网上的信息，当你需要实时性信息时使用",
                handler=self.search,
                properties={"query": {"type": "string", "description": "搜索关键词"}},
                required=["query"]
            ),
            Tool(
                name="get_time",
                description="获取当前时间，当你需要时间信息时使用，该tool无需参数",
                handler=self.get_time
            ),
            Tool(
                name="get_news",
                description="获取指定平台的基金新闻，平台代码在 new_platform.txt 中",
                handler=self.get_news,
                properties={"platform": {"type": "string",
                                         "description": f"基金新闻平台代码,新闻平台，可选值：{self.platform_list}"}},
                required=["platform"]
            ),
            Tool(
                name="get_akshare_fund_nav",
                description="获取指定基金的净值历史",
                handler=akshare_func.get_akshare_fund_nav,
                properties={"fund_code": {"type": "string", "description": "基金代码"}},
                required=["fund_code"]
            ),
            Tool(
                name="get_akshare_rank_by_type",
                description="根据基金类型获取对应的基金排名，参数可选值：全部、股票型、混合型、债券型、指数型、QDII、FOF",
                handler=akshare_func.get_akshare_rank_by_type,
                properties={"fund_type": {"type": "string", "description": "基金类型，可选值：全部、股票型、混合型、债券型、指数型、QDII、FOF"}},
                required=["fund_type"]
            ),
            Tool(
                name="get_akshare_data_by_code",
                description="根据基金代码获取akshare基金数据，若基金代码不存在则返回空字典",
                handler=akshare_func.get_akshare_data_by_code,
                properties={"fund_code": {"type": "string", "description": "基金代码"}},
                required=["fund_code"]
            ),
            Tool(
                name="get_fund_holdings",
                description="获取指定基金的持仓股票信息",
                handler=akshare_func.get_akshare_hold,
                properties={
                    "fund_code": {"type": "string", "description": "基金代码"},
                    "date": {"type": "string", "description": "报告期，如'2024'或'2025'，默认为2026"},
                },
                required=["fund_code"]
            ),
            Tool(
                name="get_akshare_stock_fund_flow",
                description="获取股票或板块的行业排行，了解当前市场关注焦点(东方财富网-沪深板块-行业板块-历史行情)",
                handler=akshare_func.get_akshare_stock_fund_flow,
                properties={},
                required=[]
            ),
            Tool(
                name="get_akshare_hot_rank",
                description="获取股票或板块的热度排行，了解当前市场关注焦点，了解“聪明钱”流向",
                handler=akshare_func.get_akshare_hot_rank,
                properties={},
                required=[]
            ),
            Tool(
                name="get_akshare_sw_index_third_info",
                description="获取申万三级行业的整体估值数据，如静态市盈率、TTM市盈率、市净率、股息率等，方便横向对比",
                handler=akshare_func.get_akshare_sw_index_third_info,
                properties={},
                required=[]
            ),
            Tool(
                name="retrieve_tool_data",
                description="从临时 SQLite 中检索之前存储的大量工具数据（如搜索结果），用关键词模糊匹配",
                handler=self.retrieve_tool_data,
                properties={
                    "query": {"type": "string", "description": "检索关键词"},
                    "top_k": {"type": "integer", "description": "返回条数，默认 5"},
                },
                required=["query"]
            ),
            Tool(
                name="sql_get_tables",
                description="获取临时 SQLite 数据库中所有表名",
                handler=self.sql_get_tables,
                required=[]
            ),
            Tool(
                name="sql_get_schema",
                description="获取指定表的字段结构",
                handler=self.sql_get_schema,
                properties={"table_name": {"type": "string", "description": "表名"}},
                required=["table_name"]
            ),
            Tool(
                name="sql_execute_query",
                description="在临时 SQLite 数据库上执行查询",
                handler=self.sql_execute_query,
                properties={
                    "sql": {"type": "string", "description": "SQL 查询语句"},
                    "limit": {"type": "integer", "description": "返回行数上限，默认 100"},
                },
                required=["sql"]
            )
        ]

    def prompt(self, session_id: str, query: str) -> str:
        return f"""
        你是一个专业的网络搜索副agent，你的任务是根据主agent的问题，获取相关的资料。
        请根据主agent分配的任务，使用各种不同的搜索工具搜索互联网，获取相关的资料，并简要回答主agent的问题。
        
        以下是可参考资料：
        时间：{self.get_time()}
        """


    # 工具方法
    def _inject_params(self, tool_name: str, params: dict, session_id: str):
        """需要 session_id 的工具在此注入。SearchAgent 无 delegate，只注入数据检索类工具。"""
        if tool_name in ("retrieve_tool_data", "sql_get_tables", "sql_get_schema", "sql_execute_query"):
            params['session_id'] = session_id
        return params
    def search(self, query: str):
        # logger.info(f"调用搜索工具🔍:search({query})")
        response = self.tavily_client.search(
            query=query,
            include_answer="basic",
            search_depth="advanced"
        )
        # logger.info(f"搜索工具🔍完成:search({query})->{response["answer"]}")
        return response["answer"]

    def get_time(self) -> str:
        return str(datetime.now())

    def get_news(self, platform: str) -> str:
        logger.info(f"get_news.{platform}")
        with httpx.Client(follow_redirects=True) as client:
            response = client.get("https://orz.ai/api/v1/dailynews", params={"platform": platform})
            data = response.json()
            logger.info(f"新闻搜索结果：{data}")
            res = data.get("status", -1)
            if str(res) == '200':
                return json.dumps(data["data"],
                                  ensure_ascii=False)  # data["data"]中返回的不是纯字符串，而Openai需要message中的content需要纯字符串，需要转换为字符串
            else:
                return "搜索失败，请强调提醒用户此次搜索失败情况"

    def _load_platforms(self) -> list[str]:
        """从 new_platform.txt 提取平台代码"""
        platforms = []
        with open(BASE_DIR / "new_platform.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 3 and parts[0].strip().isdigit():
                    platforms.append(parts[2].strip())
        return platforms

    # ── 工具数据检索 ──
    def retrieve_tool_data(self, session_id: str, query: str, top_k: int = 5) -> str:
        """从临时 SQLite 中检索已存储的工具数据（关键词 LIKE 匹配）。"""
        results = self.sqlite_tool_memory.retrieve(session_id, query, top_k)
        if not results:
            return "未在临时内存中找到相关数据，可能已被释放或数据不存在。"
        return results

    # ── Text2Sql 工具 ──
    def _get_temp_text2sql(self, session_id: str) -> Text2SqlClient:
        db_path = self.sqlite_tool_memory.get_db_path(session_id)
        return Text2SqlClient(db_path)

    def sql_get_tables(self, session_id: str) -> str:
        client = self._get_temp_text2sql(session_id)
        result = client.get_table_list()
        client.conn.close()
        return result

    def sql_get_schema(self, session_id: str, table_name: str) -> str:
        client = self._get_temp_text2sql(session_id)
        result = client.get_schema(table_name)
        client.conn.close()
        return result

    def sql_execute_query(self, session_id: str, sql: str, limit: int = 100) -> str:
        client = self._get_temp_text2sql(session_id)
        result = client.execute_sql_query(sql, limit)
        client.conn.close()
        return str(result)

import asyncio
if __name__ == '__main__':
    async def main():
        search_agent = SearchAgent()
        content, reasoning = await search_agent.chat("沈阳的天气？")
        print('---------------------')
        print(content, reasoning)
    asyncio.run(main())

