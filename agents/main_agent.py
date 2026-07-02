from agents.tools import Tool
from agents.agent_classes.orchestrator_agent import OrchestratorAgent
from .search_agent import SearchAgent
from .master_agent import MasterAgent
import functools

class MainAgent(OrchestratorAgent):
    def __init__(self):
        super().__init__()

    @property
    def tools(self) -> list[Tool]:
        return [
            Tool(
                name="agent_add_preference",
                description="记录用户的偏好、习惯或要求，供后续对话参考",
                handler=self.agent_add_preference,
                properties={
                    "query": {"type": "string", "description": "需要记录的偏好内容"},
                },
                required=["query"]
            ),
            Tool(
                name="delegate_search_subagent",
                description="委托搜索子agent",
                handler=self.delegate_search_subagent,
                properties={"task": {"type": "string", "description": "搜索任务，需要传入搜索关键词，供搜索子agent执行"}},
                required=["task"]
            ),Tool(
                name="delegate_Buffett_Warren_subagent",
                description="巴菲特 子agent，这是一位美国的投资大师，但不乏广泛的国际投资经验，具有更加普适的投资理论，该subagent通过模仿该人物的思想和方法，达到尽可能接近该人物的水平。根据用户咨询的问题，与语料库的检索工具，提供专业的回答",
                handler=functools.partial(self.delegate_master_subagent,master_name="Buffett_Warren"),
                properties={"query": {"type": "string", "description": "需要咨询的问题"}},
                required=["query"]
            ),Tool(
                name="delegate_Duan_Yongping_subagent",
                description="段永平 子agent，这是一位中国本地的投资大师，对中国市场的理解更加深入，该subagent通过模仿该人物的思想和方法，达到尽可能接近该人物的水平。根据用户咨询的问题，与语料库的检索工具，提供专业的回答",
                handler=functools.partial(self.delegate_master_subagent,master_name="Duan_Yongping"),
                properties={"query": {"type": "string", "description": "需要咨询的问题"}},
                required=["query"]
            ),Tool(
                name="delegate_Bogle_John_subagent",
                description="博格尔 子agent，这是指数基金之父，对指数基金的了解更加深入，该subagent通过模仿该人物的思想和方法，达到尽可能接近该人物的水平。根据用户咨询的问题，与语料库的检索工具，提供专业的回答",
                handler=functools.partial(self.delegate_master_subagent,master_name="Bogle_John"),
                properties={"query": {"type": "string", "description": "需要咨询的问题"}},
                required=["query"]
            )
        ]

    def prompt(self, session_id: str, query: str) -> str:
        return f"""
        你是一个智能任务分配agent，你的任务是根据用户的问题，委托给各子agent执行各种任务，并根据子agent的回复，整合结果，返回给用户。
        
        若用户问题过于简单或无法用子agent执行，请你尝试解决用户问题。
        若用户问题需要多个子agent执行，你需要根据用户问题，将任务分配给多个子agent执行，可同时执行多个子agent，若一次agent调用无法完成任务，可多轮调用子agent。
        
        你需要尽可能反复多次调用子agent，让多位投资大师之间的方法论进行博弈和辩论，产生思维碰撞，最终产生专业的回答。
        以下为可参考资料：
        对话历史：{self.memory.conversation_retriever(session_id,query,top_k=5)}
        """

    @property
    def agent_name(self):
        return "main_agent"

    def delegate_search_subagent(self,task: str,session_id: str) -> str:
        """委托搜索子agent"""
        search_agent = SearchAgent()
        return search_agent.chat(query=task,session_id=session_id+"_search_agent")       # 为避免各agent之间的对话记录冲突，需要在session_id中添加agent_name

    def agent_add_preference(self, session_id: str, query: str) -> str:
        """记录用户偏好到持久化记忆"""
        self.memory.add_preference(session_id, query)
        return "成功"

    def delegate_master_subagent(self,master_name: str,query: str,session_id: str) -> str:
        """投资大师子agent"""
        master_agent = MasterAgent(master_name)
        return master_agent.chat(query=query,session_id=session_id+f"_{master_name}_agent")       # 为避免各agent之间的对话记录冲突，需要在session_id中添加agent_name

import asyncio
async def main():
    main_agent = MainAgent()
    response = main_agent.chat("111", "你好，我想知道北京的天气")
    async for chunk in response:
        # print(chunk)
        pass
if __name__ == '__main__':
    asyncio.run(main())
