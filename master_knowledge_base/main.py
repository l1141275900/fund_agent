from env import BASE_DIR
import os
import chromadb
from sentence_transformers import SentenceTransformer  # SentenceTransformer: 将文本映射到固定维度向量空间的模型
import logging
logger = logging.getLogger("master_knowledge")
PARSED_DIR = BASE_DIR / "资源搜索" / "data" / "investment_masters_parsed"
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

BATCH_SIZE = 100

class MasterCollectionClient:
    def __init__(self):
        self.collections = {}   # 存储每个master对应的collection_client

        # 选择原则：
        #   - 中英双语场景 → paraphrase-multilingual-MiniLM-L12-v2（与项目现有模型一致）
        #   - 纯中文场景 → BAAI/bge-small-zh-v1.5（中文效果更好）
        #   - 纯英文场景 → all6-v2
        self.embedding_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        self.client = chromadb.PersistentClient(path=BASE_DIR / "master_knowledge_base" / "db")

    async def create_collection_client(self):

        all_docs = []
        for md_file in sorted(PARSED_DIR.rglob("*.md")):
            text = md_file.read_text(encoding="utf-8").strip()
            if len(text) < 50:  # 跳过极短/空文件
                continue

            # 加入文档列表
            all_docs.append({
                "master": md_file.parent.name,
                "content": text,
                "source": md_file.stem  # 文档来源文件名（不包含扩展名），对比.name返回的是完整文件名
            })

        logger.info(f"共{len(all_docs)}个文档")
        # 语义切块
        # 先遍历每个doc，对每个doc的content进行切块，切块后存入chunk列表

        # 配置splitter，递归切割
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        import hashlib
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,  # chunk_size并非硬上限，当字符超过chunk_size后但无法被切割，则会保留原大小
            chunk_overlap=100,
            length_function=len,
            separators=["\n\n", "\n", ".", "?", '!', ",", "。", "，", "！", "？", " "],
            is_separator_regex=True,
        )
        # 切分期会在保持语义完整性的基础上，尝试将文档切分成多个chunk，优先尝试separators中排名靠前的，若切分失败，则顺延下一个尝试切分，直到切分结果可以小于chunk_size
        all_chunks = []
        for doc in all_docs:
            chunks = splitter.split_text(doc["content"])
            for i, chunk in enumerate(chunks):
                id_str = f"{doc['master']}/{doc['source']}/{i:04d}"
                all_chunks.append({
                    "id": hashlib.md5(id_str.encode('utf-8')).hexdigest(),
                    "content": chunk,
                    "source": doc["source"],
                    "master": doc["master"],
                    "chunk_id": i,  # 块序号
                })

        logger.info(f"切片共{len(all_chunks)}个chunk")
        logger.info(f"平局长度{sum(len(chunk["content"]) for chunk in all_chunks) / len(all_chunks)}个字符")

        # 向量化与入库
        masters = set(chunk['master'] for chunk in all_chunks)  # 获取到全部的master
        for master in masters:
            coll_name = master.split("_")[0].lower()  # 以master名称的lowercase作为collection名称

            # get_or_create_collection: 已存在则复用，不存在则创建。metadata 仅在创建时生效
            self.collections[coll_name] = self.client.get_or_create_collection(
                name=coll_name,
                metadata={"description": f"{master}的投资方法论知识库"},
            )
            logger.info(f"知识库 {coll_name} 就绪，当前 {self.collections[coll_name].count()} 条记录")

        # 批量embedding+upsert
        # embedding 是 CPU 密集型操作，SentenceTransformer.encode() 支持批量推理
        # 把多个句子组成一个 list 一次性传入，比逐条调用快 5-10 倍


        for master_name in masters:
            coll_name = master_name.split("_")[0].lower()
            coll_client = self.collections[coll_name]
            master_chunks = [chunk for chunk in all_chunks if chunk['master'] == master_name]  # 过滤出当前master的所有chunk

            for batch_start in range(0, len(master_chunks), BATCH_SIZE):  # 遍历所有chunk，每次遍历都仅仅只是拿到BATCH的开头index
                batch = master_chunks[batch_start:batch_start + BATCH_SIZE]  # 每次取BATCH_SIZE个chunk

                # 将batch中的内容转换为chromadb中需要的格式
                ids = [chunk['id'] for chunk in batch]
                documents = [chunk['content'] for chunk in batch]
                metadatas = [{"source": chunk['source'], "chunk_id": chunk['chunk_id'], "master": chunk['master']} for chunk in batch]

                # SentenceTransformer.encode():
                #   - 入参: list[str]，批量文本
                #   - 出参: numpy.ndarray, shape=(N, 384)
                #   - 384 是 MiniLM 模型的输出向量维度
                #   - normalize_embeddings=True 将向量归一化，检索时用余弦相似度
                #   - show_progress_bar=False 关闭 tqdm 进度条（避免刷屏）
                embeddings = self.embedding_model.encode(  # 转化为向量表示
                    documents,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )

                # 向chromadb中写入
                coll_client.upsert(
                    documents=documents,
                    embeddings=embeddings.tolist(),  # ndarray → list[list[float]]
                    ids=ids,  # 若id已存在，则更新；若id不存在，则插入
                    metadatas=metadatas
                )
        logger.info(f"\n入库完成！共 {sum(coll.count() for coll in self.collections.values())} 条记录")

    # 若已经创建过了collection，可调用该方法加载collection
    def load_collection(self, master_name: str):
        coll_name = master_name.split("_")[0].lower()
        self.collections[coll_name] = self.client.get_collection(coll_name)

    def collection_retriever(self, master_name:str, query:str, top_k:int=5):
        # 处理master_name，确保与collection_name一致
        coll_name = master_name.split("_")[0].lower()
        coll_client = self.collections.get(coll_name)
        if not coll_client:
            return []

                                                            #  ↓这里必须需要一个list，即使只有一条
        query_embeddings = self.embedding_model.encode([query],normalize_embeddings=True)

        # 调用chromadb的query方法，返回top k个结果
        # ChromaDB query():
        #   - query_embeddings: 查询向量（和 query_texts 二选一）
        #   - n_results: 返回 top-k 条最相似结果
        #   - include: 返回哪些字段。documents=文本内容, metadatas=元信息,
        #              distances=距离值
        results = coll_client.query(
            query_embeddings=query_embeddings.tolist(),
            n_results=top_k,
            include=['documents','metadatas','distances']
        )

        # results 结构（有点绕）：
        # {
        #   "ids": [["id1", "id2", ...]],      # 外层 list 对应输入 query 数
        #   "documents": [["doc1", ...]],       # 这里只有 1 个 query，所以都是 1 元素
        #   "metadatas": [[{...}, ...]],
        #   "distances": [[0.23, 0.45, ...]],  # 距离越小越相似
        # }
        # 取 [0] 解掉外层 list，得到该 query 的结果
        out = []
        for i in range(len(results['ids'][0])):
            out.append({
                "id": results['ids'][0][i],
                "document": results['documents'][0][i],
                "metadata": results['metadatas'][0][i],
                "distance": results['distances'][0][i],
            })

        return out

if __name__ == '__main__':
    client = MasterCollectionClient()
    client.load_collection("Buffett_Warren")
    result = client.collection_retriever("Buffett_Warren", "投资方法论")
    print(result)

