# 阶段三引导文档：测试体系搭建

> **阶段目标**：从零搭建 pytest 测试框架，覆盖工具方法（单元测试）、Agent 循环（集成测试）、API 端点（端到端测试），让"改完代码跑一下"从人眼变成自动化。

---

## 〇、最终目标：完工后的项目结构

```
agent_learn1/
├── tests/                        # ← 新建目录
│   ├── __init__.py               #     空文件
│   ├── conftest.py               #     共享 fixtures（mock 对象等）
│   ├── test_tools.py             #     工具方法的单元测试
│   ├── test_agent_memory.py      #     AgentMemory 单元测试
│   ├── test_knowledge_base.py    #     KnowledgeInit 单元测试
│   ├── test_chat.py              #     Agent 循环集成测试
│   └── test_api.py               #     FastAPI 端点测试
├── pytest.ini                    # ← 新建：pytest 配置
├── requirements-dev.txt          # ← 新建：开发依赖
└── ...（现有文件不变）
```

打开终端，敲 `pytest -v`，看到 15-20 个绿点。

---

## 一、为什么 Agent 项目的测试和普通后端不一样

### 普通后端测试

```python
def test_add_user():
    result = add_user("张三", "zhang@example.com")
    assert result.name == "张三"
    assert result.email == "zhang@example.com"
```

输入确定 → 输出确定。写 assert 就完了。

### Agent 测试

```python
async def test_chat():
    agent = FundAgent(mock_memory, mock_kb)
    async for chunk in agent.chat("user1", "帮我分析新能源基金"):
        ...
    # 怎么 assert？LLM 的输出是随机的，今天说"建议买入"明天说"谨慎观望"
```

Agent 的测试难点在于**非确定性**。你需要把问题拆成两层：

| 层 | 测试什么 | 怎么处理非确定性 |
|------|----------|-----------------|
| **工具层** | `search("新能源基金")` 返回正确结构 | mock 掉 Tavily，输入输出完全确定 |
| **编排层** | LLM 选择了正确的工具、参数传递正确、流式 chunk 拼接正确 | mock 掉 OpenAI API，用一个**预设的确定性响应**替代 LLM |
| **端到端层** | HTTP 200、SSE 格式正确、错误时有合适的 status code | 不测答案质量，只测协议和生命周期 |

**核心原则：永远不测 LLM 的智商。** LLM 的输出质量是 eval 做的事（阶段四），不归测试管。测试只管"给定这个 LLM 响应，Agent 循环的下一个动作是否正确"。

---

## 二、核心知识点：Mock（模拟）

### 为什么需要 mock

你的 `search()` 方法依赖 Tavily API。如果不 mock：

- 每次测试都打一次真实 API → 慢、耗额度、网络挂了测试也挂
- 无法测试"API 返回异常时 Agent 怎么处理"

Mock 就是**用一个假的替代品换掉真实的外部依赖**。

### 最小示例

```python
from unittest.mock import MagicMock, patch

# 假设你的函数：
def search(query: str) -> str:
    client = TavilyClient(api_key)
    return client.search(query=query)["answer"]

# 测试它（mock 掉 TavilyClient）：
@patch("agent.TavilyClient")          # ← 凡是 agent.py 里用到 TavilyClient 的地方，都用假的
def test_search(mock_tavily_class):
    # 设置假 client 的行为
    mock_client = MagicMock()
    mock_client.search.return_value = {"answer": "这是假搜索结果"}
    mock_tavily_class.return_value = mock_client

    agent = FundAgent()               # agent.__init__ 里 TavilyClient(api_key) 会拿到假 client
    result = agent.search("测试")
    assert result == "这是假搜索结果"
```

关键理解：

- `@patch("agent.TavilyClient")` 的字符串是**目标代码中引用它的路径**，不是定义它的路径。因为 `agent.py` 里有 `from tavily import TavilyClient`，所以 patch 的路径是 `"agent.TavilyClient"`
- `MagicMock()` 是一个"万能假对象"——你调它的任何方法、访问任何属性，它都自动返回一个新的 MagicMock，不会报 AttributeError
- `.return_value` 设置调用这个 mock 时的返回值

### Mock 的三种形态

| 场景 | 工具 | 示例 |
|------|------|------|
| 替换一个类 | `@patch("agent.TavilyClient")` | 不让 search 真的连 Tavily |
| 替换一个函数 | `@patch("agent.AgentMemory")` | 不让 add_preference 真的写 ChromaDB |
| mock 一个对象的方法 | `MagicMock()` + `.return_value` | 设置假 client 的 `.search()` 返回值 |

---

## 三、前置准备

### 3.1 安装依赖

```bash
pip install pytest pytest-asyncio pytest-mock httpx
```

三个新包：

| 包 | 作用 |
|------|------|
| `pytest` | 测试框架 |
| `pytest-asyncio` | 让 pytest 支持 `async def test_xxx()` |
| `pytest-mock` | `mocker` fixture，比 `unittest.mock` 更简洁 |

创建 `requirements-dev.txt`：

```
pytest>=8.0
pytest-asyncio>=0.24
pytest-mock>=3.12
httpx>=0.27      # FastAPI TestClient 需要
```

### 3.2 创建 `pytest.ini`

```ini
[pytest]
testpaths = tests
asyncio_mode = auto
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
```

`asyncio_mode = auto` 是关键的——省得每个 async 测试函数都手动加 `@pytest.mark.asyncio`。

### 3.3 创建目录结构

```bash
mkdir tests
touch tests/__init__.py
```

---

## 四、分步实施

---

### 步骤 1：第一个测试——`get_time()` 不依赖任何外部服务

这是最适合开刀的测试——不需要 mock，纯逻辑。

**创建 `tests/test_tools.py`**：

```python
"""工具方法的单元测试"""
import pytest
from agent import FundAgent


class TestGetTime:
    """get_time() —— 最简单的纯函数，不需要 mock"""

    def test_returns_string(self):
        agent = FundAgent()
        result = agent.get_time()
        assert isinstance(result, str)

    def test_returns_non_empty(self):
        agent = FundAgent()
        result = agent.get_time()
        assert len(result) > 0

    def test_format_is_iso_like(self):
        """get_time 返回 str(datetime.now())，应该包含日期分隔符"""
        agent = FundAgent()
        result = agent.get_time()
        # str(datetime.now()) 格式类似 "2025-01-15 14:30:00.123456"
        assert "-" in result
        assert ":" in result
```

**验证**：

```bash
pytest tests/test_tools.py -v
```

**预期输出**：

```
tests/test_tools.py::TestGetTime::test_returns_string PASSED
tests/test_tools.py::TestGetTime::test_returns_non_empty PASSED
tests/test_tools.py::TestGetTime::test_format_is_iso_like PASSED
```

> **为什么这么简单的东西也要测？** 因为"简单"不等于"不会坏"。如果某天你把 `str(datetime.now())` 改成了 `datetime.now().timestamp()`（返回 float），`get_time` 的调用方（LLM）会收到一个数字而不是日期字符串。这个测试会在你改坏的当场就告诉你。另外，这是你写的第一个测试——用最简单的函数建立信心。

---

### 步骤 2：Mock 外部依赖——测试 `search()`

**在 `tests/test_tools.py` 中追加**：

```python
from unittest.mock import MagicMock, patch


class TestSearch:
    """search() —— 依赖 Tavily API，需要 mock"""

    @patch("agent.TavilyClient")
    def test_returns_answer_from_tavily(self, mock_tavily_class):
        # 设置假 TavilyClient 的行为
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "answer": "新能源基金今日表现：宁德时代涨2.3%"
        }
        mock_tavily_class.return_value = mock_client

        agent = FundAgent()
        result = agent.search("新能源基金")

        assert result == "新能源基金今日表现：宁德时代涨2.3%"

    @patch("agent.TavilyClient")
    def test_passes_query_to_tavily(self, mock_tavily_class):
        """验证 query 参数被正确传递"""
        mock_client = MagicMock()
        mock_client.search.return_value = {"answer": "ok"}
        mock_tavily_class.return_value = mock_client

        agent = FundAgent()
        agent.search("沪深300指数")

        # 断言：假 client 的 search 方法被调用时，传入了正确的参数
        mock_client.search.assert_called_once_with(
            query="沪深300指数",
            include_answer="basic",
            search_depth="advanced",
        )
```

**验证**：

```bash
pytest tests/test_tools.py::TestSearch -v
```

> **知识点：`assert_called_once_with`** —— mock 对象会记录每次调用时的参数。这让你不仅能测返回值，还能测**你的代码是否正确地把参数传给了外部依赖**。Agent 场景下这个尤其重要——如果 LLM 传了 `query="新能源基金"` 但你的代码错误地传了 `query=""`，返回值可能看起来正常但内容风马牛不相及。

---

### 步骤 3：测试 ChromaDB 依赖——`AgentMemory`

`AgentMemory` 依赖 ChromaDB 的 `PersistentClient`。ChromaDB 有 `EphemeralClient`（内存模式，测试友好），但我们用 mock 更可控。

**创建 `tests/test_agent_memory.py`**：

```python
"""AgentMemory 单元测试"""
from unittest.mock import MagicMock, patch
import pytest
from memory import AgentMemory


class TestAddPreference:
    """add_preference()"""

    @patch("memory.chromadb.PersistentClient")
    @patch("memory.embedding_functions.SentenceTransformerEmbeddingFunction")
    def test_upsert_is_called(self, mock_embed_fn, mock_chroma_class):
        """写偏好时，ChromaDB 的 upsert 被调用"""
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma_class.return_value = mock_client
        mock_embed_fn.return_value = MagicMock()

        memory = AgentMemory()
        memory.add_preference("user_001", "我喜欢简洁的回答")

        # 断言 upsert 被调用了
        assert mock_collection.upsert.called

        # 断言传入的 document 内容正确
        call_args = mock_collection.upsert.call_args[1]   # kwargs
        assert call_args["documents"][0] == "我喜欢简洁的回答"
        assert call_args["metadatas"][0]["user_id"] == "user_001"

    @patch("memory.chromadb.PersistentClient")
    @patch("memory.embedding_functions.SentenceTransformerEmbeddingFunction")
    def test_upsert_is_idempotent(self, mock_embed_fn, mock_chroma_class):
        """同一用户同一偏好写入两次，id 相同（幂等）"""
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma_class.return_value = mock_client
        mock_embed_fn.return_value = MagicMock()

        memory = AgentMemory()
        memory.add_preference("user_001", "我喜欢简洁的回答")
        memory.add_preference("user_001", "我喜欢简洁的回答")

        # 两次 upsert 调用，id 应该相同
        first_id = mock_collection.upsert.call_args_list[0][1]["ids"][0]
        second_id = mock_collection.upsert.call_args_list[1][1]["ids"][0]
        assert first_id == second_id


class TestPreferenceRetriever:
    """preference_retriever()"""

    @patch("memory.chromadb.PersistentClient")
    @patch("memory.embedding_functions.SentenceTransformerEmbeddingFunction")
    def test_returns_empty_list_when_no_results(self, mock_embed_fn, mock_chroma_class):
        """无匹配结果时返回空列表"""
        mock_collection = MagicMock()
        mock_collection.query.return_value = {"documents": [[]], "ids": [[]], "metadatas": [[]]}
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma_class.return_value = mock_client
        mock_embed_fn.return_value = MagicMock()

        memory = AgentMemory()
        result = memory.preference_retriever("user_001", "无关联查询")

        assert result == []

    @patch("memory.chromadb.PersistentClient")
    @patch("memory.embedding_functions.SentenceTransformerEmbeddingFunction")
    def test_results_sorted_by_date_desc(self, mock_embed_fn, mock_chroma_class):
        """返回的偏好按日期降序（最新的在前）"""
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["文档A", "文档B"]],
            "ids": [["id_a", "id_b"]],
            "metadatas": [[
                {"user_id": "u1", "date": "2025-01-01T00:00:00"},
                {"user_id": "u1", "date": "2025-06-15T00:00:00"},
            ]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma_class.return_value = mock_client
        mock_embed_fn.return_value = MagicMock()

        memory = AgentMemory()
        result = memory.preference_retriever("user_001", "查询")

        # 第一个应该是 6 月的（更新）
        assert result[0]["date"] == "2025-06-15T00:00:00"
        assert result[1]["date"] == "2025-01-01T00:00:00"
```

**验证**：

```bash
pytest tests/test_agent_memory.py -v
```

---

### 步骤 4：测试 Agent 循环——`chat()` 集成测试

这是整个阶段最核心的部分。你需要 mock 掉 OpenAI API，让 LLM 返回**预设的确定性响应**，然后验证 Agent 的行为。

**创建 `tests/test_chat.py`**：

```python
"""Agent 循环集成测试 —— mock OpenAI API"""
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
import json
from agent import FundAgent


# ═══════════════════════════════════════════════════════════
# 辅助工具：构造假的 OpenAI streaming chunk
# ═══════════════════════════════════════════════════════════

def make_content_chunk(text: str) -> MagicMock:
    """模拟一个包含文本内容的 streaming chunk"""
    chunk = MagicMock()
    delta = MagicMock()
    delta.content = text
    delta.reasoning_content = None
    delta.tool_calls = None
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = delta
    return chunk


def make_tool_call_chunk(index: int, tool_id: str, name: str, arguments: str) -> MagicMock:
    """模拟一个包含 tool_call 的 streaming chunk"""
    chunk = MagicMock()
    delta = MagicMock()
    delta.content = None
    delta.reasoning_content = None

    tool_call = MagicMock()
    tool_call.index = index
    tool_call.id = tool_id
    tool_call.function = MagicMock()
    tool_call.function.name = name
    tool_call.function.arguments = arguments
    delta.tool_calls = [tool_call]

    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = delta
    return chunk


# ═══════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════

class TestChatSimpleAnswer:
    """LLM 直接回答，不调用工具"""

    @patch("agent.OpenAI")
    def test_finish_prefix_ends_loop(self, mock_openai_class):
        """当 LLM 返回 [finish] 前缀的内容时，循环终止"""
        # 构造假 LLM client
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.return_value = iter([
            make_content_chunk("[finish]这是最终答案。"),
        ])
        mock_openai_class.return_value = mock_llm

        # Mock memory 和 knowledge_base
        mock_memory = MagicMock()
        mock_memory.conversation_retriever.return_value = []
        mock_memory.preference_retriever.return_value = []
        mock_kb = MagicMock()
        mock_kb.knowledge_retriever.return_value = "[]"

        agent = FundAgent()
        agent.memory = mock_memory
        agent.knowledge_base = mock_kb
        agent.llm = mock_llm

        # 收集所有 yield 的输出
        outputs = []
        async for chunk in agent.chat("user_001", "帮我分析新能源基金"):
            outputs.append(chunk)

        # 断言：有一个包含 [finish] 内容的输出
        content_outputs = [
            json.loads(o.replace("data:", "").strip())
            for o in outputs
            if o.startswith("data:")
        ]
        texts = [c["content"] for c in content_outputs if c["content"]]
        assert any("[finish]" in t for t in texts)

        # 断言：对话历史被保存了
        assert mock_memory.add_conversation.called


class TestChatWithToolCalling:
    """LLM 调用工具，Agent 执行工具并返回结果"""

    @patch("agent.OpenAI")
    def test_single_search_tool_call(self, mock_openai_class):
        """LLM 调用 search 工具，Agent 执行后继续对话"""
        mock_llm = MagicMock()

        # 第一轮 LLM 返回 → 调用 search 工具
        # 第二轮 LLM 返回 → [finish] 答案
        mock_llm.chat.completions.create.side_effect = [
            # 第一轮：tool_call + 空 content
            iter([
                make_tool_call_chunk(0, "call_001", "search", '{"query": "新能源基金"}'),
            ]),
            # 第二轮：finish
            iter([
                make_content_chunk("[finish]根据搜索结果，新能源基金今日表现良好。"),
            ]),
        ]
        mock_openai_class.return_value = mock_llm

        mock_memory = MagicMock()
        mock_memory.conversation_retriever.return_value = []
        mock_memory.preference_retriever.return_value = []
        mock_kb = MagicMock()
        mock_kb.knowledge_retriever.return_value = "[]"

        agent = FundAgent()
        # 把 search 换成假实现，避免真实 Tavily 调用
        agent.search = MagicMock(return_value="新能源基金今日涨2.3%")
        agent.memory = mock_memory
        agent.knowledge_base = mock_kb
        agent.llm = mock_llm

        outputs = []
        async for chunk in agent.chat("user_001", "帮我查新能源基金"):
            outputs.append(chunk)

        # 断言：search 工具被调用了
        agent.search.assert_called_once_with(query="新能源基金")

        # 断言：tool calling 的 yield 信息被发送了
        tool_calling_info = [
            json.loads(o.replace("data:", "").strip())["tool_calling"]
            for o in outputs
            if o.startswith("data:") and json.loads(o.replace("data:", "").strip()).get("tool_calling")
        ]
        assert len(tool_calling_info) > 0
        assert "search" in tool_calling_info[0]


class TestChatWithUnknownTool:
    """LLM 请求了不存在的工具"""

    @patch("agent.OpenAI")
    def test_unknown_tool_raises_keyerror(self, mock_openai_class):
        """请求未知工具时抛出 KeyError"""
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.side_effect = [
            iter([
                make_tool_call_chunk(0, "call_001", "nonexistent_tool", '{}'),
            ]),
        ]
        mock_openai_class.return_value = mock_llm

        mock_memory = MagicMock()
        mock_memory.conversation_retriever.return_value = []
        mock_memory.preference_retriever.return_value = []
        mock_kb = MagicMock()
        mock_kb.knowledge_retriever.return_value = "[]"

        agent = FundAgent()
        agent.memory = mock_memory
        agent.knowledge_base = mock_kb
        agent.llm = mock_llm

        with pytest.raises(KeyError, match="未知工具"):
            async for _ in agent.chat("user_001", "测试"):
                pass
```

**验证**：

```bash
pytest tests/test_chat.py -v
```

> **技术要点：`side_effect`** —— 当 LLM 需要多轮交互时（第一轮 tool call → 第二轮 finish），`side_effect` 接受一个列表，每次调用按顺序返回列表中的下一个值。这让你可以精确控制 Agent 循环中每一轮 LLM 的行为。

---

### 步骤 5：测试 FastAPI 端点

**创建 `tests/test_api.py`**：

```python
"""FastAPI 端点测试"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from app import app


@pytest.fixture
def mock_agent():
    """创建一个假的 FundAgent，chat 返回预设的 streaming 数据"""
    async def fake_chat(user_id: str, query: str):
        yield "data:{\"content\": \"你好\", \"reasoning_content\": null, \"tool_calling\": null}\n\n"

    agent = MagicMock()
    agent.chat = fake_chat
    return agent


@pytest.mark.asyncio
async def test_chat_endpoint_returns_200(mock_agent):
    """POST /chat/query 返回 200"""
    # 替换 app.state.agent 为假 agent
    app.state.agent = mock_agent

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/chat/query", json={
            "user_id": "test_user",
            "query": "你好"
        })

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_chat_endpoint_validates_request():
    """缺少必填字段时返回 422"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/chat/query", json={
            "user_id": "test_user"
            # 缺少 query
        })

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_endpoint_sse_format(mock_agent):
    """返回的 SSE 格式正确（以 data: 开头）"""
    app.state.agent = mock_agent

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/chat/query", json={
            "user_id": "test_user",
            "query": "你好"
        })

    body = response.text
    assert body.startswith("data:")
    assert body.endswith("\n\n")
```

**验证**：

```bash
pytest tests/test_api.py -v
```

> **关于 `pytest.fixture`**：`mock_agent` 是一个 fixture——pytest 自动在需要它的测试函数中注入。它在这里的作用是创建一个假 Agent，避免测试 API 时真的走一遍 Agent 循环。

---

### 步骤 6：Schema 验证测试

Pydantic model 的验证逻辑也应该测——尤其是边界情况。

**在 `tests/` 下创建 `test_schema.py`**：

```python
"""Pydantic Schema 验证测试"""
import pytest
from pydantic import ValidationError
from schema.chat import ChatRequest


class TestChatRequest:
    def test_valid_request(self):
        req = ChatRequest(user_id="user_001", query="你好")
        assert req.user_id == "user_001"
        assert req.query == "你好"

    def test_missing_query_raises_error(self):
        with pytest.raises(ValidationError):
            ChatRequest(user_id="user_001")   # 缺少 query

    def test_missing_user_id_raises_error(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="你好")          # 缺少 user_id

    def test_empty_query_is_allowed(self):
        """Pydantic 默认不拒绝空字符串，除非加 min_length"""
        req = ChatRequest(user_id="u1", query="")
        assert req.query == ""
```

---

## 五、`conftest.py`——消除重复的 mock 代码

随着测试增多，你会发现很多测试都在重复创建 mock 的 memory 和 kb。把它们提取到 `conftest.py`：

**创建 `tests/conftest.py`**：

```python
"""共享 fixtures —— 所有测试文件自动可用"""
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_memory():
    """假的 AgentMemory —— conversation_retriever 和 preference_retriever 都返回空"""
    memory = MagicMock()
    memory.conversation_retriever.return_value = []
    memory.preference_retriever.return_value = []
    return memory


@pytest.fixture
def mock_kb():
    """假的 KnowledgeInit —— knowledge_retriever 返回空 JSON 数组"""
    kb = MagicMock()
    kb.knowledge_retriever.return_value = "[]"
    return kb
```

然后 `test_chat.py` 里的测试就可以简化：

```python
# 改造前：
mock_memory = MagicMock()
mock_memory.conversation_retriever.return_value = []
mock_memory.preference_retriever.return_value = []
mock_kb = MagicMock()
mock_kb.knowledge_retriever.return_value = "[]"

# 改造后 —— pytest 自动注入 fixture：
def test_xxx(self, mock_memory, mock_kb):
    agent = FundAgent()
    agent.memory = mock_memory
    agent.knowledge_base = mock_kb
```

---

## 六、测试金字塔（你的项目）

```
         ┌──────┐
         │ E2E  │  test_api.py         3 个测试  ← 慢，但保证协议正确
         ├──────┤
         │ 集成  │  test_chat.py         3 个测试  ← 核心，验证 Agent 循环逻辑
         ├──────┤
         │ 单元  │  test_tools.py         6 个测试
         │      │  test_agent_memory.py   4 个测试
         │      │  test_knowledge_base.py 2 个测试
         │      │  test_schema.py         4 个测试
         └──────┘                         共约 22 个测试
```

运行一次全部测试：**< 2 秒**（因为全部 mock 了外部依赖，不联网，不读磁盘上的 ChromaDB）。

---

## 七、步骤依赖

```
步骤1 (get_time 测试)  ← 先写最简单的一个，建立信心
  ↓
步骤2 (search 测试)    ← 学会 @patch
  ↓
步骤3 (memory 测试)    ← mock 更复杂的依赖（ChromaDB）
  ↓
步骤4 (chat 集成测试)  ← 最难但最重要——mock OpenAI streaming
  ↓
步骤5 (API 测试)       ← FastAPI TestClient + AsyncMock
  ↓
步骤6 (schema 测试)    ← 最简单的放最后当收尾
```

---

## 八、自我检查清单

- [ ] `pip install pytest pytest-asyncio pytest-mock httpx` 安装成功
- [ ] `pytest tests/ -v` 所有测试通过，无 skipped
- [ ] 每个测试文件至少有 2 个测试用例
- [ ] `test_chat.py` 里有一个测试 mock 了 OpenAI streaming 响应
- [ ] `test_chat.py` 里有一个测试验证了工具被正确调用（`assert_called_once_with`）
- [ ] `conftest.py` 里有 `mock_memory` 和 `mock_kb` 两个 fixture
- [ ] 所有测试不联网、不读写磁盘 ChromaDB（保证 < 3 秒跑完）
