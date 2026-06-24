
from pydantic import Field,BaseModel


class FundsRequest(BaseModel):
    fund_code:str = Field(...,description="基金代码")