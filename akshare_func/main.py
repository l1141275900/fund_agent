import asyncio
import threading
import akshare as ak

# akshare 底层依赖 py_mini_racer (V8)，多线程并发调用会导致 V8 isolate 初始化冲突崩溃
_ak_lock = threading.Lock()

# 暴露给llm与前端接口
def get_akshare_data_by_code(fund_code:str):
    """
    根据基金代码获取akshare基金数据，若基金代码不存在则返回空字典
    """
    with _ak_lock:
        data = ak.fund_overview_em(symbol=fund_code)
    if data["基金全称"][0] == '---':
        return {}
    return data.to_dict('records')[0]

# 暴露给llm与前端接口
def get_akshare_rank_by_type(fund_type:str):
    """
    获取所有akshare基金排名，根据基金类型
    可选值：全部、股票型、混合型、债券型、指数型、QDII、FOF
    """
    valid_types = ["全部","股票型","混合型","债券型","指数型","QDII","FOF"]
    if fund_type not in valid_types:
        return {}
    with _ak_lock:
        data = ak.fund_open_fund_rank_em(symbol=fund_type)
    return data.to_dict('records')

# 暴露给llm与前端接口
def get_akshare_fund_nav(fund_code:str):
    """
    获取单个akshare基金净值历史
    """
    with _ak_lock:
        data = ak.fund_open_fund_info_em(symbol=fund_code)
    return data.to_dict('records')

# 暴露给llm与前端接口
def get_akshare_hold(fund_code:str,date:str="2026"):
    """
    获取单个akshare基金持仓
    """
    with _ak_lock:
        data = ak.fund_portfolio_hold_em(symbol=fund_code,date=date)
    return data.to_dict('records')

# 接口供应商的ip被ban了，所以不能用这个接口
def get_akshare_fund_area(fund_code:str):
    """
    根据code获取基金行业
    """
    data = ak.stock_bid_ask_em(symbol=fund_code)
    return data

def get_industries():
    """
    获取所有行业
    """
    data = ak.stock_individual_basic_info_xq(symbol="688147")
    return data.to_dict('records')

def get_akshare_hot_rank():
    """
    获取股票或板块的热度排行，了解当前市场关注焦点
    """
    data = ak.stock_hot_rank_em()
    return data.to_dict('records')

def get_akshare_sw_index_third_info():
    """
    获取申万三级行业的整体估值数据，如静态市盈率、TTM市盈率、市净率、股息率等，方便横向对比
    """
    data = ak.sw_index_third_info()
    return data.to_dict('records')

def get_akshare_stock_fund_flow():
    """
    获取股票或板块的行业排行，了解当前市场关注焦点(东方财富网-沪深板块-行业板块-历史行情)
    """
    data = ak.stock_fund_flow_industry(symbol="3日排行")
    return data.to_dict('records')

if __name__ == '__main__':
    result = get_akshare_stock_fund_flow()
    print(result)
