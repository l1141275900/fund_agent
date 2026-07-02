import asyncio
import functools
import json
import logging
import os
from abc import abstractmethod
from typing import Callable

from openai import OpenAI

from schema.output import format_output
from tool_memory import SqliteToolMemory, summarize_data
from agents.tools import Tool


DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

logger = logging.getLogger("agent")


class BaseAgent:
    def __init__(self):
        self.sqlite_tool_memory = SqliteToolMemory()
        self.llm = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )

    @property
    @abstractmethod
    def tools(self) -> list[Tool]:
        pass

    @abstractmethod
    def prompt(self, session_id: str, query: str) -> str:
        pass

    @property
    @abstractmethod
    def agent_name(self):
        pass


    async def _persist_turn(self, session_id: str, user_query: str, agent_response: str):
        """钩子方法，持久化当前轮次的对话记录，只需要在main_agent中被重写使用"""
        pass

    def _inject_params(self, tool_name: str, params: dict, session_id: str):
        """钩子方法，注入 session_id 等上下文参数。子类覆写以指定需要注入的 tool。"""
        return params


    def _tool_handlers(self, tool_name):
        for tool_obj in self.tools:
            if tool_obj.name == tool_name:
                return tool_obj.handler
        raise KeyError(f"LLM请求了错误的工具:{tool_name}")

    async def _safe_execute_func(self, handler: Callable, params: dict):
        try:
            func = functools.partial(handler, **params)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, func)
            return {
                "raw": result,
                "str": str(result) if result is not None else "调用成功，tool无返回值"
            }
        except Exception as e:
            logger.error(f"调用工具失败：{e}")
            return {"raw": None, "str": f"调用工具失败：{e}"}

    async def chat(self, session_id: str, query: str):
        print(f"agent {self.agent_name} 开始处理查询：{query}")
        messages_list = [{"role": "user", "content": query}]

        for time in range(10):
            logger.info(f"Agent[{self.agent_name}] 第{time + 1}轮")
            response = self.llm.chat.completions.create(
                model="deepseek-v4-flash",
                messages=[
                    {"role": "system", "content": self.prompt(session_id, query)},
                    *messages_list,
                ],
                tools=[tool.to_openai_schema() for tool in self.tools],
                tool_choice="auto",
                stream=True,
            )

            # 处理流式响应
            full_content = ""
            tool_call_dict = {}
            for chunk in response:
                message = chunk.choices[0].delta

                if message.content: # 若有主要输出，则处理并yield
                    full_content += message.content
                    print(message.content, end="")
                    yield format_output(json.dumps({
                        "content": message.content,
                        "reasoning_content": None,
                        "tool_calling": None,
                        "tool_call_result": None,
                        "agent_name": self.agent_name,
                        "turn": time + 1,
                    }))

                # 处理推理内容
                if hasattr(message, "reasoning_content") and message.reasoning_content:
                    print(message.reasoning_content, end="")
                    yield format_output(json.dumps({
                        "content": None,
                        "reasoning_content": message.reasoning_content,
                        "tool_calling": None,
                        "tool_call_result": None,
                        "agent_name": self.agent_name,
                        "turn": time + 1,
                    }))

                if message.tool_calls:      #若有工具调用，则将tool calling合并入tool_call_dict，相同index的tool calling合并arguments
                    for tool_item in message.tool_calls:
                        idx = tool_item.index
                        if idx not in tool_call_dict:   # 若是新index，直接添加
                            tool_call_dict[idx] = tool_item
                        else:   # 若是旧index，合并arguments
                            tool_call_dict[idx].function.arguments += tool_item.function.arguments

            tool_call_list = [func_item for func_item in tool_call_dict.values()]   # 将tool_call_dict转换为列表
            assistant_reply = full_content[8:] if full_content.startswith("[finish]") else full_content

            # 若没有工具调用或结束标记出现，则表示当前所有内容都已经生成完成，结束本轮对话
            if not tool_call_list or full_content.startswith("[finish]"):
                await asyncio.get_event_loop().run_in_executor(     # 若没有工具调用或查询结束，清空会话（清除此次用于存储大量查询数据的sqlite数据库）
                    None, self.sqlite_tool_memory.clear_session, session_id
                )
                await self._persist_turn(session_id, query, assistant_reply)  # 持久化本轮对话记录
                break

            messages_list.append({"role": "assistant", "content": full_content or ""})  # 将本轮回复添加到消息列表

            async for result in self._execute_tools(tool_call_list, messages_list, session_id, time + 1):
                yield result  # 将工具调用结果yield给前端或父 Agent

    async def _execute_tools(self, tool_call_list, messages_list, session_id, turn=0):
        """
        执行本轮所有 tool 调用，yield SSE 帧。

        BaseAgent 默认实现：所有 tool 走线程池，asyncio.gather 并行执行。
        OrchestratorAgent 覆写此方法，加入 delegate/subagent 路由。
        """
        loop = asyncio.get_event_loop()

        messages_list[-1]["tool_calls"] = [
            {
                "id": tc.id, "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in tool_call_list
        ]

        tool_tasks = []
        for func in tool_call_list:
            func_setting = func.function
            real_func = self._tool_handlers(func_setting.name)
            logger.info(f"Agent[{self.agent_name}] 调用方法：{func_setting.name}，参数：{func_setting.arguments}")
            params = json.loads(func_setting.arguments)
            params = self._inject_params(func_setting.name, params, session_id)

            yield format_output(json.dumps({
                "content": None, "reasoning_content": None,
                "tool_calling": f"{func_setting.name}({func_setting.arguments})",
                "tool_call_result": None, "agent_name": self.agent_name,
                "turn": turn,
            }))

            tool_tasks.append(self._safe_execute_func(real_func, params))

        result = await asyncio.gather(*tool_tasks)
        for i, item in enumerate(result):
            raw = item["raw"]
            content = item["str"]
            tool_name = tool_call_list[i].function.name

            if (isinstance(raw, list) and len(raw) > SqliteToolMemory.LARGE_LIST_THRESHOLD) or \
               (isinstance(raw, str) and len(raw) > 3000):
                n_rows = await loop.run_in_executor(
                    None, self.sqlite_tool_memory.store_result,
                    session_id, tool_name, raw
                )
                content = summarize_data(raw, tool_name)
                logger.info(f"Agent[{self.agent_name}] 工具 {tool_name} 返回大数据，{n_rows} 行已存 SQLite")

            messages_list.append({
                "role": "tool",
                "tool_call_id": tool_call_list[i].id,
                "content": content,
            })
            yield format_output(json.dumps({
                "content": None, "reasoning_content": None,
                "tool_calling": f"{tool_call_list[i].function.name}({tool_call_list[i].function.arguments})",
                "tool_call_result": content, "agent_name": self.agent_name,
                "turn": turn,
            }))

    # async def subagent_run(self, session: str, query: str):
    #     now_content = ""
    #     now_reasoning = ""
    #     async for chunk in self.chat(session, query):
    #         chunk_json = json.loads(chunk[5:].strip())
    #
    #         now_content += chunk_json.get("content") or ""
    #         now_reasoning += chunk_json.get("reasoning_content") or ""
    #         yield chunk  # 原样透传给父 Agent / 前端
    #
    #     # 流结束，将累积的全量内容和推理提交给主 Agent
    #     yield format_output(json.dumps({
    #         "content": None,
    #         "reasoning_content": None,
    #         "tool_calling": None,
    #         "tool_call_result": None,
    #         "agent_name": self.agent_name,
    #         "now_content": now_content,
    #         "now_reasoning": now_reasoning,
    #     }))
