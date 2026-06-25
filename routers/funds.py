from fastapi import APIRouter
from schema.funds import FundsRequest,FundRankRequest,FundHoldRequest,SubmitFundRequest
import logging
from akshare_func.main import get_akshare_data_by_code,get_akshare_rank_by_type,get_akshare_fund_nav,get_akshare_hold
from sqlite_db.fund_collection import FundCollectionClient

router = APIRouter(prefix="/fund", tags=["fund"])    #prefix添加统一路径前缀   tags为丝袜哥文档添加tag
logger = logging.getLogger("agent")


@router.get('/query_fund')
def query_fund(fund_code: str):
    # 根据基金代码查询基金详情（同步 def，FastAPI 自动丢线程池，不阻塞事件循环）
    return get_akshare_data_by_code(fund_code)

@router.get('/get_fund_rank')
def get_fund_rank(fund_type: str):
    # 获取基金排行
    return get_akshare_rank_by_type(fund_type)

@router.get("/get_fund_nav")
def get_fund_nav(fund_code: str):
    # 获取单个基金净值历史
    return get_akshare_fund_nav(fund_code)

@router.get("/get_fund_hold")
def get_fund_hold(fund_code: str, date: str):
    # 获取基金的持仓情况
    return get_akshare_hold(fund_code, date)

@router.put("/submit_fund")
async def submit_fund(res: SubmitFundRequest):
    """
    提交基金数据，用户选择当前持有基金->上传到数据库->后续分析
    """
    fund_collection = FundCollectionClient()
    fund_code_list = res.fund_code_list

    result_list = []
    for item in fund_code_list:
        result_list.append((item["基金代码"],item["基金简称"],item["基金类型"],item["基金经理人"],item["基金管理人"],item["净资产规模"],item["管理费率"],item["成立日期/规模"].split("/")[0].strip()))

    # code,name,fund_type,manager,company,scale,fee_rate,created_at

    result = fund_collection.insert_funds(result_list)
    fund_collection.close()
    return result


@router.get("/holdings")
async def get_holdings():
    """获取用户全部已持有基金列表"""
    fund_collection = FundCollectionClient()
    fund_collection.create_funds_db()
    result = fund_collection.query_all_funds()
    fund_collection.close()
    return [dict(row) for row in result]


@router.delete("/remove_fund")
async def remove_fund(fund_code: str):
    """删除单只基金"""
    fund_collection = FundCollectionClient()
    result = fund_collection.delete_funds(fund_code)
    fund_collection.close()
    return result


