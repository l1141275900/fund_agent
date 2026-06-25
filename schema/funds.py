
from pydantic import Field,BaseModel


class FundsRequest(BaseModel):
    fund_code:str = Field(...,description="基金代码")

class FundRankRequest(BaseModel):
    fund_type:str = Field(...,description="基金类型，可选值：全部、股票型、混合型、债券型、指数型、QDII、FOF")

class FundHoldRequest(BaseModel):
    fund_code:str = Field(...,description="基金代码")
    date:str = Field(...,description="日期")

class SubmitFundRequest(BaseModel):
    fund_code_list:list = Field(...,description="基金代码列表，需要将query_fund接口返回的内容全部拼接")
