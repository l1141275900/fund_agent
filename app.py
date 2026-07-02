import os
# 使用 HuggingFace 国内镜像，避免下载慢/超时
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

# from agent import FundAgent
from agents.main_agent import MainAgent
import logging
from routers.router import router as main_router
from routers.funds import router as fund_router
from memory import AgentMemory
from sqlite_db.fund_collection import FundCollectionClient
from sqlite_db.chat_history import ChatHistoryClient

from master_knowledge_base.main import MasterCollectionClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agent")


@asynccontextmanager
async def lifespan(app:FastAPI):
    logger.info("预加载1.加载知识库。可能需要一些时间")
    # app.state.memory = memory       #app.state是app的全局状态，整个应用可以访问，这里是要交给router里使用
    # app.state.knowledge_base = kb
    app.state.agent = MainAgent()
    # await load_json(app.state.agent.knowledge_base)
    # logger.info("知识库加载完成")
    logger.info("预加载2.加载基金持有数据库")
    app.state.fund_collection_client = FundCollectionClient()
    await app.state.fund_collection_client.create_funds_db()
    logger.info("基金持有数据库加载完成")
    logger.info("预加载3.加载对话历史数据库")
    history_client = ChatHistoryClient()
    history_client.create_tables()
    history_client.close()
    logger.info("对话历史数据库加载完成")
    logger.info("预加载4.加载投资家知识库")
    master_knowledge_client = MasterCollectionClient()
    await master_knowledge_client.create_collection_client()
    logger.info("投资家知识库加载完成")
    yield
    logger.info("卸载资源")

app = FastAPI(title="基金分析Agent", version="1.0.0", lifespan=lifespan)

app.include_router(main_router)
app.include_router(fund_router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return RedirectResponse(url="/static/index.html")
