from fastapi import FastAPI,APIRouter,Request
from fastapi.responses import StreamingResponse
from schema.chat import ChatRequest,QueryResponse
from sqlite_db.chat_history import ChatHistoryClient
import logging
import asyncio


router = APIRouter(prefix="/chat", tags=["chat"])    #prefix添加统一路径前缀   tags为丝袜哥文档添加tag
logger = logging.getLogger("agent")


@router.post('/query')
async def chat(res: ChatRequest, request: Request):
    # 保存用户消息（同步调用，不跨线程）
    user_client = ChatHistoryClient()
    user_client.save_user_message(res.session_id, res.query)
    user_client.close()

    async def wrapped():
        # wrapped 由 StreamingResponse 调度到独立线程执行
        # 必须新建 client，不能共享外层线程的 SQLite 对象
        import json as _json
        stream_client = ChatHistoryClient()
        full_content = ""
        async for chunk in request.app.state.agent.chat(res.session_id, res.query):
            yield chunk
            # 从 SSE 帧中提取 content 字段，累积做历史记录
            try:
                c = chunk.strip()
                if c.startswith("data:"):
                    c = c[5:]
                data = _json.loads(c)
                if data.get("content"):
                    full_content += data["content"]
            except Exception:
                pass
        # 流结束后保存 assistant 消息（同步调用，本就在 streaming 线程内）
        if full_content.strip():
            stream_client.save_assistant_message(res.session_id, full_content.strip())
        stream_client.close()

    return StreamingResponse(
        content=wrapped(),
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