import hashlib
import json
import logging
import os
import re
import sqlite3
import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path

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


class SqliteToolMemory:
    """结构化大数据的 SQLite 临时存储。

    akshare 返回的 list[dict] 是表格数据，用 SQLite 关键词检索替代 ChromaDB embedding，
    存储从 2-5 分钟降至 <1 秒，检索从 ~100ms 降至 <10ms。
    """

    LARGE_LIST_THRESHOLD = 15
    DATA_DIR = Path("./tool_data")

    def __init__(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _db_path(self, session_id: str) -> str:
        return str(self.DATA_DIR / f"{session_id}.db")

    def get_db_path(self, session_id: str) -> str:
        """获取 session 对应的 SQLite 文件路径（供 Text2SqlClient 使用）。"""
        return self._db_path(session_id)

    def _connect(self, session_id: str):
        conn = sqlite3.connect(self._db_path(session_id))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _safe_table_name(tool_name: str) -> str:
        return "t_" + re.sub(r'[^a-zA-Z0-9_一-鿿]', '_', tool_name)[:50]

    def store_result(self, session_id: str, tool_name: str, raw_data) -> int:
        """将工具返回数据存入 SQLite。list[dict] 存为表，str 按行切块存入。返回行数。"""
        if not raw_data:
            return 0

        # 字符串：按换行切块，每行存为一个 chunk
        if isinstance(raw_data, str):
            lines = [l for l in raw_data.split("\n") if l.strip()]
            if not lines:
                lines = [raw_data]  # 只有一行也存
            raw_data = [{"content": line} for line in lines]

        if not isinstance(raw_data, list):
            return 0

        conn = self._connect(session_id)
        try:
            table = self._safe_table_name(tool_name)
            sample = raw_data[0]
            if isinstance(sample, dict):
                columns = list(sample.keys())
            else:
                columns = ["value"]
                raw_data = [{"value": str(item)} for item in raw_data]

            # 清理字段名中的特殊字符
            col_defs = []
            clean_cols = []
            for col in columns:
                clean = re.sub(r'[^a-zA-Z0-9_一-鿿]', '_', str(col))[:40]
                clean_cols.append(clean)
                col_defs.append(f'"{clean}" TEXT')

            # DROP 旧表 + CREATE 新表 + INSERT
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
            conn.execute(f'CREATE TABLE "{table}" ({", ".join(col_defs)})')

            placeholders = ", ".join(["?" for _ in clean_cols])
            quoted_cols = ", ".join(f'"{c}"' for c in clean_cols)
            rows = []
            for item in raw_data:
                if isinstance(item, dict):
                    rows.append([str(item.get(col, "")) for col in columns])
                else:
                    rows.append([str(item)])

            conn.executemany(f'INSERT INTO "{table}" ({quoted_cols}) VALUES ({placeholders})', rows)
            conn.commit()
            logger.info(f"[sqlite_tool] 存入 {tool_name}: {len(rows)} 行 -> 表 {table} (session={session_id})")
            return len(rows)
        finally:
            conn.close()

    def retrieve(self, session_id: str, query: str, top_k: int = 5) -> str:
        """关键词 LIKE 检索，返回格式化结果。"""
        db_path = self._db_path(session_id)
        if not os.path.exists(db_path):
            return ""

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # 获取所有表名
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()]
            if not tables:
                return ""

            results = []
            # 提取 query 中的关键词（按空格、标点分词）
            keywords = [kw for kw in re.split(r'[\s,，。；;、]+', query) if len(kw) >= 1]

            for table in tables:
                # 获取该表的文本列
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
                if not cols:
                    continue

                # 构建 LIKE 条件
                if keywords:
                    conditions = " OR ".join([f'"{c}" LIKE ?' for c in cols for kw in keywords])
                    params = [f"%{kw}%" for c in cols for kw in keywords]
                    sql = f'SELECT * FROM "{table}" WHERE {conditions} LIMIT {top_k}'
                else:
                    sql = f'SELECT * FROM "{table}" LIMIT {top_k}'
                    params = []

                cursor = conn.execute(sql, params)
                for row in cursor.fetchall():
                    item = dict(row)
                    results.append("\n".join(f"{k}: {v}" for k, v in item.items()))
                    if len(results) >= top_k:
                        break
                if len(results) >= top_k:
                    break

            return "\n---\n".join(results) if results else ""
        finally:
            conn.close()

    def clear_session(self, session_id: str):
        """删除 session 对应的临时数据库文件。"""
        db_path = self._db_path(session_id)
        try:
            if os.path.exists(db_path):
                os.remove(db_path)
                logger.info(f"[sqlite_tool] 已释放 session={session_id} 的临时数据库")
        except Exception as e:
            logger.error(f"[sqlite_tool] 释放失败: {e}")


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
