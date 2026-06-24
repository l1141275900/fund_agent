import json
from typing import Dict

import chromadb
from chromadb.utils import embedding_functions
import logging
from env import BASE_DIR

logger = logging.getLogger("agent")

class KnowledgeInit:
    def __init__(self,persist_path:str=BASE_DIR / "knowledge"):
        self.client = chromadb.PersistentClient(persist_path)
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="paraphrase-multilingual-MiniLM-L12-v2")

        self.knowledge_collection = self.client.get_or_create_collection(
            name="knowledge_collection",
            embedding_function=self.embedding_fn
        )

    async def add_knowledge(self,query:Dict[str,list]):
        self.knowledge_collection.upsert(**query)

    def knowledge_retriever(self,query:str,top_k:int=3):
        result = self.knowledge_collection.query(
            query_texts=query,  # 向量匹配
            n_results=top_k
        )
        # logger.info(result["documents"][0])
        if not result["documents"][0]:
            return "[]"

        return json.dumps(result["documents"][0])