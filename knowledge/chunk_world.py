import json
from pathlib import Path
import asyncio
from typing import Dict
from env import MAX_DATA_SIZE
import logging

from knowledge.knowledge_base import KnowledgeInit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agent")

from env import BASE_DIR
async def load_json(kb:KnowledgeInit,data_dir:str=BASE_DIR / "data" / "资源搜索/data"):
    """
        读取所有的json并返回拼接结果
    """

    batch_size = 100
    for json_path in Path(data_dir).glob("*.jsonl"):        # Path(data_dir).glob("*.jsonl")会返回一个迭代器，效果类似于 ls xxx
        with open(json_path,"r",encoding="utf-8") as f:
            non_empty_lines = sum(1 for line in f if line.strip())  #统计行数，python的生成表达式和迭代器特性支持这样的写法
            logger.info(f"共有{non_empty_lines}条数据，限制加载{MAX_DATA_SIZE}")

            f.seek(0)   #重置文件指针

            batch_chunks:Dict[str,list] = {
                "ids":[],
                "documents":[],
                'metadatas':[]
            }
            count = 0
            for line in f:  # 在python的for循环中，对文件进行for循环，一次只读一行
                line = json.loads(line)

                # 将格式转换为chromadb需要的样子
                batch_chunks["ids"].append(str(line['id']))
                batch_chunks["documents"].append(f"标题：{line['title']}。发布者：{line['author']}。发布时间{line['published_at']}。tags:{line['tags']}。正文:{line['content']}。url: {line['url']}")
                batch_chunks['metadatas'].append({
                    "source": line["source"],
                    "tags": line['tags']
                })

                if len(batch_chunks["ids"]) >= batch_size:
                    await kb.add_knowledge(batch_chunks)  # 提交至向量数据库
                    count += len(batch_chunks["ids"])
                    logger.info(f"加载知识库{count}/{non_empty_lines} | {((count / non_empty_lines) * 100):.2f}%")
                    batch_chunks = {
                        "ids": [],
                        "documents": [],
                        'metadatas': []
                    }

                    if count >= MAX_DATA_SIZE:  #达到测试需求量
                        break

            if len(batch_chunks["ids"]):        # 若文件加载完毕以后还有部分内容没有加入向量库
                await kb.add_knowledge(batch_chunks)  # 提交至向量数据库
                count += len(batch_chunks["ids"])
                logger.info(f"加载知识库{count}/{non_empty_lines} | {((count / non_empty_lines) * 100):.2f}%")

if __name__ == '__main__':
    asyncio.run(load_json())

