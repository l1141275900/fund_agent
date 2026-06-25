from typing import Callable

from memory import AgentMemory
from knowledge.knowledge_base import KnowledgeInit
from openai import OpenAI
import os
from tavily import TavilyClient
import httpx
from datetime import datetime
from schema.output import format_output
import json
import logging
import asyncio
import functools
from dataclasses import dataclass, field
from env import BASE_DIR
from sqlite_db.fund_collection import FundCollectionClient
import akshare_func.main as akshare_func
from tool_memory import ToolResultMemory, summarize_data
from sqlite_db.chat_history import ChatHistoryClient

logger = logging.getLogger("agent")

# 环境配置
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

@dataclass
class Tool:
    name:str
    description:str
    handler:Callable    # 实际执行的方法
    properties:dict = field(default_factory=dict)   #为确保每次创建时都是新的dict/list等可变类型，在使用dataclass后必须要使用field
    required:list = field(default_factory=list)

    def to_openai_schema(self) -> dict:
        """生成 OpenAI Function Calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.properties,
                    "required": self.required
                }
            }
        }

class FundAgent:
    def __init__(self):
        self.memory = AgentMemory()
        self.knowledge_base = KnowledgeInit()
        self.tavily_client = TavilyClient(TAVILY_API_KEY)
        self.tool_memory = ToolResultMemory()
        self.chat_history = ChatHistoryClient()

        self.llm = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
        self.platform_list = self._load_platforms()
        self.fund_collection_client = FundCollectionClient()
        self.tools:list[Tool] = [
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
                name="knowledge_retriever",
                description="使用向量数据库检索基金相关内容，向量数据库中是各部门的财报等各种与基金股票相关的金融研报，若返回值中有你认为相关的内容，可以通过url进行搜索",
                handler=self.knowledge_retriever,
                properties={
                    "query": {"type": "string", "description": "需要进行向量匹配的字段"},
                    "top_k": {"type": "integer", "description": "需要返回的数据条数，一般为5，必要时可进行调整"}
                },
                required=["query"]
            ),
            Tool(
                name="get_news",
                description="获取指定平台的基金新闻，平台代码在 new_platform.txt 中",
                handler=self.get_news,
                properties={"platform": {"type": "string", "description": f"基金新闻平台代码,新闻平台，可选值：{self.platform_list}"}},
                required=["platform"]
            ),
            Tool(
                name="agent_add_preference",
                description="添加用户偏好，用于后续推荐",
                handler=self.agent_add_preference,
                properties={"query": {"type": "string", "description": "用户偏好"}},
                required=["query"]
            ),
            Tool(
                name="get_all_funds",
                description="获取用户目前持有的所有基金数据",
                handler=self.fund_collection_client.query_all_funds,
                properties={},
                required=[]
            ),
            Tool(
                name="get_funds_by_code",
                description="根据基金代码查询用户持有的基金数据，若用户未持有该基金，则返回空列表",
                handler=self.fund_collection_client.query_funds_by_code,
                properties={"code": {"type": "string", "description": "基金代码"}},
                required=["code"]
            ),
            Tool(
                name="insert_one_fund_by_code",
                description="使用基金代码将基金数据插入到用户持有的数据库中，当你需要更新用户持有的基金数据时使用",
                handler=self.fund_collection_client.insert_one_fund_by_code,
                properties={"fund_code": {"type": "string", "description": "基金代码"}},
                required=["fund_code"]
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
                description="根据基金类型获取对应的基金排名，参数可选值：全部、股票型、混合型、债券型、指数型、QDII、FOF，若返回值为空则说明参数错误",
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
                properties={"fund_code": {"type": "string", "description": "基金代码"},
                            "date": {"type": "string", "description": "报告期，如'2024'或'2025'，默认为2026"}},
                required=["fund_code"]
            ),
            Tool(
                name="retrieve_tool_data",
                description="从临时内存中检索之前工具调用返回的大量数据切片。当数据量过大被自动切片存储后，用此工具按自然语言查询条件检索相关切片。",
                handler=self.retrieve_tool_data,
                properties={
                    "query": {"type": "string", "description": "自然语言检索查询，描述需要从已存储数据中查找什么"},
                    "top_k": {"type": "integer", "description": "返回切片数量，默认5"}
                },
                required=["query"]
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
            )
        ]


    # 工具方法
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

    # Openai中，所有方法被调用的记录都要传入，而方法调用的结果也要返回给llm
    def agent_add_preference(self, session_id: str, query: str) -> str:
        self.memory.add_preference(session_id, query)
        return "成功"

    def get_news(self, platform: str)->str:
        logger.info(f"get_news.{platform}")
        with httpx.Client(follow_redirects=True) as client:
            response = client.get("https://orz.ai/api/v1/dailynews", params={"platform": platform})
            data = response.json()
            logger.info(f"新闻搜索结果：{data}")
            res = data.get("status", -1)
            if res == '200':
                return json.dumps(data["data"], ensure_ascii=False)     #data["data"]中返回的不是纯字符串，而Openai需要message中的content需要纯字符串，需要转换为字符串
            else:
                return "搜索失败，请强调提醒用户此次搜索失败情况"

    def knowledge_retriever(self, query: str, top_k: int = 3) -> str:
        return self.knowledge_base.knowledge_retriever(query, top_k)

    # 内部方法
    def _load_platforms(self) -> list[str]:
        """从 new_platform.txt 提取平台代码"""
        platforms = []
        with open(BASE_DIR / "new_platform.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # 只提取以数字序号开头的行（即表格数据行）
                parts = line.split("\t")
                if len(parts) >= 3 and parts[0].strip().isdigit():
                    platforms.append(parts[2].strip())
        return platforms

    def retrieve_tool_data(self, session_id: str, query: str, top_k: int = 5) -> str:
        """从临时内存中检索已存储的工具数据切片。"""
        results = self.tool_memory.retrieve(session_id, query, top_k)
        if not results:
            return "未在临时内存中找到相关数据，可能已被释放或数据不存在。"
        return "\n---\n".join(results)

    def _tool_handlers(self,tool_name):
        for tool_obj in self.tools:
            if tool_obj.name == tool_name:
                return tool_obj.handler
        raise KeyError(f"LLM请求了错误的工具:{tool_name}")

    @staticmethod
    def _should_chunk(raw_data) -> bool:
        """判断工具返回数据是否需要切片存储。"""
        if raw_data is None:
            return False
        if isinstance(raw_data, list) and len(raw_data) > ToolResultMemory.LARGE_LIST_THRESHOLD:
            return True
        if isinstance(raw_data, str) and len(raw_data) > ToolResultMemory.LARGE_STR_THRESHOLD:
            return True
        return False

    async def _safe_execute_func(self,handler:Callable,params:dict):
        try:
            func = functools.partial(handler,**params)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, func)         # loop.run_in_executor的前面如果有await，则会阻塞主线程，直到func执行完毕，并返回执行结果，而若没有await，则会立即返回一个Future对象，等待后续被调用
            return {
                "raw": result,
                "str": str(result) if result is not None else "调用成功，tool无返回值"
            }
        except Exception as e:
            logger.error(f"调用工具失败：{e}")
            return {"raw": None, "str": f"调用工具失败：{e}"}


    async def chat(self,session_id:str,query:str):
        # 保存用户消息到 SQLite 历史
        await asyncio.get_event_loop().run_in_executor(
            None, self.chat_history.save_user_message, session_id, query
        )

        # 构建初始messages
        messages_list = [{
            "role": "user", "content": query
        }]

        conversation_history = self.memory.conversation_retriever(session_id, query)  # 获取对话历史

        # 知识库向量检索
        query_knowledge = self.knowledge_base.knowledge_retriever(query=query)

        for time in range(10):
            logger.info(f"第{time + 1}次调用")
            user_preference = self.memory.preference_retriever(session_id, query)  # 获取用户偏好
            response = self.llm.chat.completions.create(
                model="deepseek-v4-flash",
                messages=[
                    {"role": "system",
                     "content": f"""
                     你是一个智能问答助手，请你尽可能利用搜索工具来回答用户关于时效性的问题。

                     1.你可以同时调用多个tool，每个tool可以调用不止一次
                     2.<strong>当你认为你已经收集了足够的信息后，你的输出应以[finish]为前缀，将你的输出放在[finish]后面</strong>。例如：[finish]*你的回答*

                     以下为可参考资料：
                     相关资料:{query_knowledge}
                     对话历史：{conversation_history}
                     用户偏好(已按最近-最远排序，最新的用户偏好在第一位，最新的用户偏好有更多的思考权重)：{user_preference}
                     """},
                    *messages_list
                ],
                tools=[tool.to_openai_schema() for tool in self.tools],
                tool_choice="auto",
                stream=True,
            )

            full_content = ""
            tool_call_dict = {}
            for chunk in response:
                message = chunk.choices[0].delta  # 回复内容中有许多例如token消耗等别的信息，只取此次回复

                if message.content:
                    full_content += message.content
                    print(message.content, end="")
                    yield format_output(json.dumps({
                        "content": message.content,
                        "reasoning_content": None,
                        "tool_calling": None,
                        "tool_call_result": None
                    }))

                # 调用工具时，不会返回reasoning_content
                if hasattr(message, "reasoning_content") and message.reasoning_content:  # 更安全地获取对象是否有某一属性
                    print(message.reasoning_content, end="")
                    yield format_output(json.dumps({
                        "content": None,
                        "reasoning_content": message.reasoning_content,
                        "tool_calling": None,
                        "tool_call_result": None
                    }))

                if message.tool_calls:
                    # 处理tool调用，因为tool调用会持久返回，故要去重
                    for tool_item in message.tool_calls:
                        # print(tool_item)
                        idx = tool_item.index  # 获取唯一标识符（实际上是llm调用的顺序）
                        if idx not in tool_call_dict:
                            tool_call_dict[idx] = tool_item  # 压入调用列表
                        else:
                            tool_call_dict[
                                idx].function.arguments += tool_item.function.arguments  # 因argument是流式输出的，故需要拼接

            tool_call_list = [func_item for func_item in tool_call_dict.values()]  # 字典的默认遍历结果是key

            # 提取助手最终回复（去掉 [finish] 前缀）
            assistant_reply = full_content[8:] if full_content.startswith('[finish]') else full_content

            if not tool_call_list:  # 没有工具调用和输出[finish]的原因都是一样的：此次输出已经结束
                self.memory.add_conversation(session_id=session_id, user_query=query, agent_response=str(messages_list[1:]))
                await asyncio.get_event_loop().run_in_executor(None, self.chat_history.save_assistant_message, session_id, assistant_reply.strip())
                await asyncio.get_event_loop().run_in_executor(None, self.tool_memory.clear_session, session_id)
                break
            elif full_content.startswith('[finish]'):
                self.memory.add_conversation(session_id=session_id, user_query=query, agent_response=str(messages_list[1:]))
                await asyncio.get_event_loop().run_in_executor(None, self.chat_history.save_assistant_message, session_id, assistant_reply.strip())
                await asyncio.get_event_loop().run_in_executor(None, self.tool_memory.clear_session, session_id)
                break
            else:
                # 将AI回复与tool调用信息压入对话历史，message.tool_calls可能为None
                messages_list.append({"role": "assistant", "content": full_content or ""})

                # 开始处理tool调用相关内容
                if tool_call_list is not None:  # 若此次有工具调用，则处理工具调用相关内容
                    loop = asyncio.get_event_loop()  # 准备异步方法调用空方法
                    tool_tasks = []
                    # 修复流式模式下 tool_call 对象可能丢失 type 字段的问题
                    # 不直接存 SDK 对象，而是手动转成 API 要求的 dict 格式
                    messages_list[-1]["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_call_list
                    ]
                    for func in tool_call_list:
                        # 解析方法名和方法参数
                        func_setting = func.function
                        real_func = self._tool_handlers(func_setting.name)  # 得到AI想要调用的方法本身
                        logger.info(f"调用方法：{func_setting.name}，参数：{func_setting.arguments}")
                        params = json.loads(        # 解析参数为json格式
                            func_setting.arguments)  # 这里应该使用json.loads，因为llm输出永远是str（arguments='{"query": "沈阳天气 今天"}'）

                        yield format_output(json.dumps({
                            "content": None,
                            "reasoning_content": None,
                            "tool_calling": f"{func_setting.name}({func_setting.arguments})",
                            "tool_call_result": None
                        }))

                        if func_setting.name in ("agent_add_preference", "retrieve_tool_data"):
                            params['session_id'] = session_id

                        tool_tasks.append(self._safe_execute_func(real_func, params))

                    result = await asyncio.gather(*tool_tasks)  # 将此次需要执行的方法并行执行
                    for i, item in enumerate(result):
                        raw = item["raw"]
                        content = item["str"]
                        tool_name = tool_call_list[i].function.name

                        # 大数据自动切片存入临时内存
                        if self._should_chunk(raw):
                            n_chunks = await loop.run_in_executor(
                                None, self.tool_memory.store_result,
                                session_id, tool_name, raw
                            )
                            content = summarize_data(raw, tool_name)
                            logger.info(f"[agent] 工具 {tool_name} 返回大数据，已切片 {n_chunks} 份存入临时内存")

                        messages_list.append({"role": "tool", "tool_call_id": tool_call_list[i].id, "content": content})
                        yield format_output(json.dumps({
                            "content": None,
                            "reasoning_content": None,
                            "tool_calling": f"{tool_call_list[i].function.name}({tool_call_list[i].function.arguments})",
                            "tool_call_result": content
                        }))

        # 对话循环结束（耗尽或异常），兜底释放临时内存
        await asyncio.get_event_loop().run_in_executor(None, self.tool_memory.clear_session, session_id)


if __name__ == '__main__':
    agent = FundAgent()
    list1 = [tool.to_openai_schema() for tool in agent.tools]
    print(list1)
