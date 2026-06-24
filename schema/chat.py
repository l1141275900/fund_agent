from pydantic import Field,BaseModel


class ChatRequest(BaseModel):
    session_id:str = Field(...,description="本意是session_id，但不好重新改了")
    query:str = Field(...,description="用户的提问")

class QueryResponse(BaseModel):
    content:str = Field(description="AI的回答")
    reasoning_content:str = Field(description="AI的思考")
    tool_calling:str = Field(description="AI的工具调用信息")