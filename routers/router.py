from fastapi import FastAPI,APIRouter,Request
from fastapi.responses import StreamingResponse
from schema.chat import ChatRequest,QueryResponse
import logging


router = APIRouter(prefix="/chat", tags=["chat"])    #prefix添加统一路径前缀   tags为丝袜哥文档添加tag
logger = logging.getLogger("agent")


@router.post('/query')
async def chat(res: ChatRequest, request: Request):
    return StreamingResponse(
        content=request.app.state.agent.chat(res.session_id,res.query),
        media_type="text/event-stream"
    )