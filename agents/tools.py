from dataclasses import dataclass, field
from typing import Callable


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


def knowledge_retriever(self, query: str, top_k: int = 3) -> str:
    """语义检索知识库，保留在 tools.py 供旧 agent.py 使用"""
    return self.knowledge_base.knowledge_retriever(query, top_k)