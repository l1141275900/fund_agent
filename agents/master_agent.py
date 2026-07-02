from agents.tools import Tool
from master_knowledge_base.main import MasterCollectionClient
from agents.agent_classes.base_agent import BaseAgent
import functools

class MasterAgent(BaseAgent):
    def __init__(self,master_name:str):
        super().__init__()
        self.master_name = master_name
        self.client = MasterCollectionClient()
        self.client.load_collection(self.master_name)

    @property
    def agent_name(self):
        return self.master_name


    def prompt(self, session_id: str, query: str) -> str:
        return f"""
            假定你是{self.master_name}，你是一个投资领域专家，请你根据客户咨询的问题，与语料库的检索工具，提供专业的回答。
        """

    @property
    def tools(self) -> list[Tool]:
        return [
            Tool(
                name="collection_retriever",
                description="根据客户咨询的问题，从语料库中检索相关文档",
                handler=functools.partial(self.client.collection_retriever,master_name=self.master_name),
                properties={"query": {"type": "string", "description": "资料库语义查询关键字"},"top_k":{"type": "integer", "description": "返回的文档数量，默认返回5个"}},
                required=["query"]
            )
        ]

