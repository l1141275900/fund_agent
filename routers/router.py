from fastapi import FastAPI,APIRouter,Request
from fastapi.responses import StreamingResponse
from schema.chat import ChatRequest,QueryResponse
from sqlite_db.chat_history import ChatHistoryClient
import logging


router = APIRouter(prefix="/chat", tags=["chat"])    #prefix添加统一路径前缀   tags为丝袜哥文档添加tag
logger = logging.getLogger("agent")


@router.post('/query')
async def chat(res: ChatRequest, request: Request):
    return StreamingResponse(
        content=request.app.state.agent.chat(res.session_id,res.query),
        media_type="text/event-stream"
    )


@router.get("/sessions")
async def get_sessions():
    """获取所有对话 session 列表"""
    client = ChatHistoryClient()
    result = client.get_sessions()
    client.close()
    return result


@router.get("/messages")
async def get_messages(session_id: str):
    """获取指定 session 的所有消息"""
    client = ChatHistoryClient()
    result = client.get_messages(session_id)
    client.close()
    return result


@router.delete("/session")
async def delete_session(session_id: str):
    """删除指定 session 及所有消息"""
    client = ChatHistoryClient()
    client.delete_session(session_id)
    client.close()
    return "ok"