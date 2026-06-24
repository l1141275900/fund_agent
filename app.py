import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI

from agent import FundAgent
from knowledge.chunk_world import load_json
import logging
from routers.router import router
from memory import AgentMemory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agent")


@asynccontextmanager
async def lifespan(app:FastAPI):
    logger.info("预加载")
    # app.state.memory = memory       #app.state是app的全局状态，整个应用可以访问，这里是要交给router里使用
    # app.state.knowledge_base = kb
    app.state.agent = FundAgent()
    await load_json(app.state.agent.knowledge_base)
    yield
    logger.info("卸载资源")

app = FastAPI(title="基金分析Agent", version="1.0.0", lifespan=lifespan)

app.include_router(router)