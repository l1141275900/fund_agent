from agent import FundAgent
import pytest
from unittest.mock import MagicMock, patch

class TestGetTime:
    def test_returns_no_empty(self):
        agent = FundAgent()
        assert len(agent.get_time()) > 0

    def test_returns_string(self):
        agent = FundAgent()
        assert isinstance(agent.get_time(),str)

    def test_returns_correct_format(self):
        agent = FundAgent()
        time = agent.get_time()
        assert "-" in time and ":" in time

class TestSearch:
    # 将agent.py里的TavilyClient替换为mock类，而class类会通过参数传递，实例需要使用MagicMock实例化
    @patch("agent.TavilyClient")
    def test_returns_answer_from_tavily(self,mock_tavily_class):
        """验证 search工具的返回内容是否能正确被处理"""
        mock_client = MagicMock()       # mock的实例化对象
        mock_client.search.return_value = {     # 定义mock对象(TavilyClient)的search返回值行为，模拟client.search
            "answer": "新能源基金今日表现：宁德时代涨2.3%"
        }
        mock_tavily_class.return_value = mock_client    #因为agent下的FundAgent会调用TavilyClient()，故这里将定义好的模拟TavilyClient()的mock对象返回的实例化对象

        agent = FundAgent()
        assert agent.search("新能源基金表现？") == "新能源基金今日表现：宁德时代涨2.3%"      #测试从客户端返回到输出结果是否能走通

    @patch("agent.TavilyClient")
    def test_passes_query_to_tavily(self,mock_tavily_class):
        """验证 query 参数被正确传递"""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "answer":"ok"
        }
        mock_tavily_class.return_value = mock_client    #将mock类注入为agent.TavilyClient

        agent = FundAgent()
        agent.search("沪深300指数")

        mock_client.search.assert_called_once_with(
            query="沪深300指数",
            include_answer="basic",
            search_depth="advanced",
        )

from memory import AgentMemory
class TestAddPreference:
    """add_preference()"""

    @patch("memory.chromadb.PersistentClient")
    @patch("memory.embedding_functions.SentenceTransformerEmbeddingFunction")
    def test_upsert_is_called(self, mock_embed_fn, mock_chroma_class):      # 装饰器会从内向外执行，故内层装饰器会注入第一个参数
        """写偏好时，检测ChromaDB 的 upsert 被调用"""
        mock_embedding = MagicMock()
        mock_client = MagicMock()

        mock_client.get_or_create_collection.return_value = mock_embedding





if __name__ == '__main__':
    pass
