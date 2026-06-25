import hashlib
import json
import logging
import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger("agent")


class ToolResultMemory:
    """大体积工具返回值的临时内存存储。

    当 akshare 等数据源工具返回大量数据时（如基金排名、净值历史），
    自动切片存入 ChromaDB，LLM 可通过 retrieve_tool_data 工具按需检索，
    session 结束时自动释放。
    """

    CHUNK_SIZE_CHARS = 2000
    CHUNK_OVERLAP = 200
    LARGE_LIST_THRESHOLD = 15
    LARGE_STR_THRESHOLD = 3000
    UPSERT_BATCH_SIZE = 200

    def __init__(self, persist_path="./tool_memory"):
        self.client = chromadb.PersistentClient(persist_path)
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="paraphrase-multilingual-MiniLM-L12-v2"
        )
        self.collection = self.client.get_or_create_collection(
            name="tool_results",
            embedding_function=self.embedding_fn,
        )

    @staticmethod
    def _serialize_item(item) -> str:
        if isinstance(item, dict):
            return "\n".join(f"{k}: {v}" for k, v in item.items())
        return str(item)

    def store_result(self, session_id: str, tool_name: str, raw_data) -> int:
        """将工具返回数据切片后存入 ChromaDB，返回切片数量。"""
        if isinstance(raw_data, list):
            chunks = [self._serialize_item(item) for item in raw_data]
        elif isinstance(raw_data, str) and len(raw_data) > self.LARGE_STR_THRESHOLD:
            chunks = []
            for start in range(0, len(raw_data), self.CHUNK_SIZE_CHARS - self.CHUNK_OVERLAP):
                chunks.append(raw_data[start:start + self.CHUNK_SIZE_CHARS])
        else:
            chunks = [str(raw_data)]

        if not chunks:
            return 0

        ids = []
        documents = []
        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_id = hashlib.md5(
                f"{session_id}:{tool_name}:{i}".encode()
            ).hexdigest()
            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({
                "session_id": session_id,
                "tool_name": tool_name,
                "chunk_index": i,
                "total_chunks": len(chunks),
            })

        for start in range(0, len(chunks), self.UPSERT_BATCH_SIZE):
            end = start + self.UPSERT_BATCH_SIZE
            self.collection.upsert(
                ids=ids[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )
        logger.info(f"[tool_memory] 存入 {tool_name}: {len(chunks)} 个切片 (session={session_id})")
        return len(chunks)

    def retrieve(self, session_id: str, query: str, top_k: int = 5) -> list[str]:
        """语义检索已存储的工具数据切片。"""
        result = self.collection.query(
            query_texts=query,
            n_results=top_k,
            where={"session_id": session_id},
        )
        if not result["documents"] or not result["documents"][0]:
            return []
        return result["documents"][0]

    def clear_session(self, session_id: str):
        """释放指定 session 的所有工具数据内存。"""
        try:
            self.collection.delete(where={"session_id": session_id})
            logger.info(f"[tool_memory] 已释放 session={session_id} 的工具数据内存")
        except Exception as e:
            logger.error(f"[tool_memory] 释放内存失败: {e}")


def summarize_data(raw_data, tool_name: str) -> str:
    """为 LLM 生成存储数据的摘要，告知数据概况及检索方式。"""
    if isinstance(raw_data, list):
        n = len(raw_data)
        field_names = list(raw_data[0].keys()) if n > 0 and isinstance(raw_data[0], dict) else []
        examples = raw_data[:3] if n > 0 else []
        example_str = "\n".join(
            ToolResultMemory._serialize_item(ex) for ex in examples
        )
        return (
            f"[工具 {tool_name} 返回了 {n} 条数据，已自动切片存入临时内存]\n"
            f"数据字段: {', '.join(field_names)}\n"
            f"前 {len(examples)} 条示例:\n{example_str}\n"
            f"---\n如需查看具体数据，请使用 retrieve_tool_data 工具，"
            f"用自然语言描述你的查询条件。"
        )
    elif isinstance(raw_data, str):
        return (
            f"[工具 {tool_name} 返回了长文本（{len(raw_data)} 字符），已自动切片存入临时内存]\n"
            f"文本开头: {raw_data[:500]}...\n"
            f"---\n如需查看具体内容，请使用 retrieve_tool_data 工具检索。"
        )
    return str(raw_data)
