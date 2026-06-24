import asyncio
import akshare as ak

# 暴露给llm与前端接口
async def get_akshare_data_by_code(fund_code:str):
    """
    根据基金代码获取akshare基金数据
    """
    data = await asyncio.to_thread(ak.fund_overview_em,symbol=fund_code)
    if data["基金全称"][0] == '---':
        return {}
    return data.to_dict('records')

# 暴露给llm与前端接口
async def get_akshare_rank_by_type(fund_type:str):
    """
    获取所有akshare基金排名，根据基金类型
    可选值：全部、股票型、混合型、债券型、指数型、QDII、FOF
    """
    data = await asyncio.to_thread(ak.fund_open_fund_rank_em,symbol=fund_type)
    return data.to_dict('records')

# 暴露给llm与前端接口
async def get_akshare_fund_nav(fund_code:str):
    """
    获取单个akshare基金净值历史
    """
    data = await asyncio.to_thread(ak.fund_open_fund_info_em,symbol=fund_code)
    return data.to_dict('records')

# 暴露给llm与前端接口
async def get_akshare_hold(fund_code:str,date:str="2026"):
    """
    获取单个akshare基金持仓
    """
    data = await asyncio.to_thread(ak.fund_portfolio_hold_em,symbol=fund_code,date=date)
    return data.to_dict('records')

if __name__ == '__main__':
    data = asyncio.run(get_akshare_data_by_code("024738"))
    print(data)
