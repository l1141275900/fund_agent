"""OrchestratorAgent — 主调度 Agent，覆写 _execute_tools 实现 tool 分类路由 + 并行 subagent 委托 + 流式多路汇聚。

继承 BaseAgent 的 chat() 循环，只替换 tool 执行层：
  delegate_* 前缀 → subagent 委托，asyncio.create_task 并行 + Queue 流式透传
  其他 tool      → 普通调用，asyncio.gather + 线程池并行执行
"""

import json
import asyncio
import logging
from abc import abstractmethod

from agents.agent_classes.base_agent import BaseAgent
from memory import AgentMemory
from agents.tools import Tool
from tool_memory import SqliteToolMemory, summarize_data


logger = logging.getLogger("agent")

# 标记 subagent 流结束的哨兵
_SENTINEL = object()


class OrchestratorAgent(BaseAgent):
    """并行委托 + 流式多路汇聚的 Orchestrator。"""
    def __init__(self):
        super().__init__()
        self.memory = AgentMemory()

    async def _persist_turn(self, session_id: str, user_query: str, agent_response: str):
        """持久化当前轮次的对话记录，重写父类方法，将对话记录存储到内存中"""
        # loop = asyncio.get_event_loop()
        self.memory.add_conversation(session_id, user_query, agent_response)

    async def _execute_tools(self, tool_call_list, messages_list, session_id, turn=0):
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

        # ── 阶段 1：分类 tool，发 tool_calling 帧 ──
        delegate_infos = []  # (i, func, handler, params)
        regular_infos = []   # (i, func, handler, params)

        for i, func in enumerate(tool_call_list):
            func_setting = func.function
            real_func = self._tool_handlers(func_setting.name)
            logger.info(f"Agent[{self.agent_name}] 调用：{func_setting.name}，参数：{func_setting.arguments}")
            params = json.loads(func_setting.arguments)
            params = self._inject_params(func_setting.name, params, session_id)

            yield self._tool_calling_frame(func_setting, turn)

            if func_setting.name.startswith("delegate_"):
                delegate_infos.append((i, func, real_func, params))
            else:
                regular_infos.append((i, func, real_func, params))

        # ── 阶段 2：并行执行普通 tool + 委托 subagent ──
        results = {}  # {index: content}

        # 2a. 普通 tool：asyncio.gather 并行执行（线程池）
        if regular_infos:
            regular_tasks = [self._safe_execute_func(handler, params)
                            for _, _, handler, params in regular_infos]
            regular_raw = await asyncio.gather(*regular_tasks)
            for (idx, func, handler, params), item in zip(regular_infos, regular_raw):      # zip将regular_infos和regular_raw对应起来，返回一个元组迭代器
                raw = item["raw"]
                content = item["str"]
                tool_name = func.function.name

                if (isinstance(raw, list) and len(raw) > SqliteToolMemory.LARGE_LIST_THRESHOLD) or \
                   (isinstance(raw, str) and len(raw) > 3000):
                    n_rows = await loop.run_in_executor(
                        None, self.sqlite_tool_memory.store_result,
                        session_id, tool_name, raw
                    )
                    content = summarize_data(raw, tool_name)
                    logger.info(f"Agent[{self.agent_name}] 工具 {tool_name} 返回大数据，{n_rows} 行已存 SQLite")

                results[idx] = content

        # 2b. 委托 tool：Queue 多路汇聚，实时透传
        if delegate_infos:
            queue = asyncio.Queue()

            async def _run_one(idx, func_obj, handler, params):              # 单个subagent的执行协程，这个函数不会直接返回结果，而是通过修改queue队列，最终通过消费queue队列来获取结果
                """单个 subagent 的执行协程：产出 chunk → 入队，最后入队哨兵 + 结果。"""
                content_parts = []
                try:
                    async for chunk in handler(**params):       # 执行subagent，产出chunk
                        content_parts.append(self._extract_content(chunk))  #从subagent的chunk中提取content
                        await queue.put((idx, chunk, None))    # (index, chunk, 结果占位)
                    result_text = "".join(content_parts)
                    await queue.put((idx, _SENTINEL, result_text))
                except Exception as e:
                    logger.error(f"subagent [{idx}] 执行失败：{e}")
                    await queue.put((idx, _SENTINEL, f"subagent 执行失败：{e}"))

            tasks = [       # FIXME:(非修复高亮)将协程封装为任务并立即调度执行（与携程有本质区别：携程是创建任务，是惰性的，需要await或asyncio.run()等来执行，而任务这里立即调度执行）
                asyncio.create_task(_run_one(i, func, handler, params))
                for i, func, handler, params in delegate_infos
            ]

            finished = set()
            while len(finished) < len(delegate_infos):
                idx, payload, result_text = await queue.get()
                if payload is _SENTINEL:
                    finished.add(idx)   #标记该subagent执行完成
                    results[idx] = result_text
                else:
                    # 流式 chunk → 改写 turn 为父 Agent 轮次后透传
                    yield self._rewrite_turn(payload, turn)

            await asyncio.gather(*tasks, return_exceptions=True)

        # ── 阶段 3：按 LLM 调用顺序写回 messages_list 并产出 tool_result 帧 ──
        for i, func in enumerate(tool_call_list):
            content = results.get(i, "")
            tool_name = func.function.name
            messages_list.append({
                "role": "tool",
                "tool_call_id": func.id,
                "content": content,
            })
            yield self._tool_result_frame(tool_name, func.function.arguments, content, turn)

    def _rewrite_turn(self, chunk: str, turn: int) -> str:
        """将 SSE 帧中的 turn 字段改写为父 Agent 的当前轮次。"""
        c = chunk.strip()
        if c.startswith("data:"):
            c = c[5:]
        try:
            data = json.loads(c)
            data["turn"] = turn
            from schema.output import format_output
            return format_output(json.dumps(data))
        except json.JSONDecodeError:
            return chunk  # 非 JSON 帧原样返回

    def _extract_content(self, chunk) -> str:
        """从 SSE 帧中提取 content 字段。"""
        try:
            if not isinstance(chunk, str):
                return ""
            c = chunk.strip()
            if c.startswith("data:"):
                c = c[5:]
            data = json.loads(c)
            return data.get("content") or ""
        except json.JSONDecodeError:
            return ""

    # ── 钩子：子类可覆写 ──

    def _inject_params(self, tool_name: str, params: dict, session_id: str):
        # delegate_* 前缀匹配所有委托工具，避免新增 subagent 时遗漏
        if tool_name in ("agent_add_preference", "retrieve_tool_data",
                         "sql_get_tables", "sql_get_schema", "sql_execute_query") \
           or tool_name.startswith("delegate_"):    #方法名以delegate_开头的工具为subagent调用，都需要注入session_id，而其他工具中，若在注入列表中，也需要注入session_id
            params['session_id'] = session_id
        return params

    def _tool_calling_frame(self, func_setting, turn=0) -> str:
        from schema.output import format_output
        return format_output(json.dumps({
            "content": None, "reasoning_content": None,
            "tool_calling": f"{func_setting.name}({func_setting.arguments})",
            "tool_call_result": None, "agent_name": self.agent_name,
            "turn": turn,
        }))

    def _tool_result_frame(self, tool_name: str, arguments: str, content: str, turn=0) -> str:
        from schema.output import format_output
        return format_output(json.dumps({
            "content": None, "reasoning_content": None,
            "tool_calling": f"{tool_name}({arguments})",
            "tool_call_result": content, "agent_name": self.agent_name,
            "turn": turn,
        }))


    # 为了应付父类的抽象方法，子类必须覆写
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
