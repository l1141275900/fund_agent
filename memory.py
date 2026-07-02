import hashlib
import logging
import chromadb
from chromadb.utils import embedding_functions
from datetime import datetime

logger = logging.getLogger("agent")

class AgentMemory:
    def __init__(self,persist_path:str = "./memory"):
        self.client = chromadb.PersistentClient(persist_path)
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="paraphrase-multilingual-MiniLM-L12-v2")

        # 根据功能创建集合
        self.conversations_collection = self.client.get_or_create_collection(
            name="conversation_history",
            embedding_function=self.embedding_fn
        )
        self.prefs_collection = self.client.get_or_create_collection(
            name="prefs_collection",
            embedding_function=self.embedding_fn
        )

    def add_preference(self,session_id:str,prefer_str:str):
        memory_id = hashlib.md5(f"{session_id}:{prefer_str}".encode()).hexdigest()     # 这样设计id是为了“幂等性”，即：若有重复的内容想要插入，则id会重复，不必产生冗余记忆。另：使用.encode()是因为hashlib仅可传入byte
        self.prefs_collection.upsert(
            ids=[memory_id],
            documents=[prefer_str],
            metadatas=[{                # 这里的metadata是自己按需建立的键值对，多用来where查询过滤
                "session_id":session_id,
                "type":"preference",
                "date":datetime.now().isoformat()
            }]
        )
    def add_conversation(self,session_id:str,user_query:str,agent_response:str):
        memory_id = hashlib.md5(f"{session_id}:{user_query}:{agent_response}".encode()).hexdigest()
        self.conversations_collection.upsert(       # 这里有一个embeddings参数但是没传，是因为embeddings参数用来传入已经编码好的内容，跳过编码
            ids=[memory_id],
            documents=[f"用户问题：{user_query}\nagent回答：{agent_response}"],
            metadatas=[{
                "session_id": session_id,
                "type": "conversation",
                "date": datetime.now().isoformat()
            }]
        )
    def preference_retriever(self,session_id:str,query:str,top_k:int=3):
        result = self.prefs_collection.query(
            query_texts=query,      # 向量匹配
            n_results=top_k*2,
            where={"session_id":session_id}   # 按值匹配
        )

        if not result["documents"][0]:
            return []

        prefs = []
        for i,doc_id in enumerate(result['ids'][0]):
            prefs.append({
                "doc_id":doc_id,
                "document":result["documents"][0][i],
                "date":result["metadatas"][0][i]['date']
            })
        prefs.sort(key=lambda x:x['date'],reverse=True)

        return prefs

    def conversation_retriever(self,session_id:str,query:str,top_k:int=3):
        result = self.conversations_collection.query(
            query_texts=query,
            n_results=top_k,
            where={"session_id":session_id}
        )
        logger.info(f"对话历史：{result['documents'][0]}")
        if not result["documents"][0]:
            return []
        return result["documents"][0]

