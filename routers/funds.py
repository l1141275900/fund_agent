from fastapi import APIRouter,Request
from fastapi.responses import StreamingResponse
from schema.funds import FundsRequest
import logging
from akshare_func.main import get_akshare_data_by_code

router = APIRouter(prefix="/chat", tags=["chat"])    #prefix添加统一路径前缀   tags为丝袜哥文档添加tag
logger = logging.getLogger("agent")


@router.post('/funds')
async def funds(res: FundsRequest):
    return StreamingResponse(
        content=await get_akshare_data_by_code(res.fund_code),
        media_type="text/event-stream"
    )