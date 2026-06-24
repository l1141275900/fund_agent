# 阶段二引导文档：工具系统重构

> **一句话目标**：把工具的定义、查找、执行三者焊成一个不可分割的整体，让"加新工具"从改三处变成改一处。

---

## 〇、最终目标：完工后的 `agent.py` 长什么样

在开始之前，先看终点。以下是改造完成后 `agent.py` 的核心骨架：

```python
# agent.py（改造完成后的形态）

from dataclasses import dataclass, field
from typing import Callable

# ═══════════════════════════════════════════════════════════
# 1. Tool —— 把 schema + handler + 元数据焊成一个对象
# ═══════════════════════════════════════════════════════════

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable
    required: list[str] = field(default_factory=list)

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }


# ═══════════════════════════════════════════════════════════
# 2. FundAgent —— 唯一的工具注册表是 self.tools 列表
# ═══════════════════════════════════════════════════════════

class FundAgent:
    def __init__(self):
        self.memory = AgentMemory()
        self.knowledge_base = KnowledgeInit()
        self.tavily_client = TavilyClient(TAVILY_API_KEY)
        self.llm = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
        self.platform_list = self._load_platforms()

        # ★ 这是整个类的唯一定义点 —— 所有工具信息在这里
        self.tools: list[Tool] = [
            Tool(
                name="search",
                description="使用搜索引擎检索信息",
                parameters={"query": {"type": "string", "description": "搜索关键词"}},
                required=["query"],
                handler=self.search,
            ),
            Tool(
                name="get_time",
                description="获取当前日期",
                parameters={},
                handler=self.get_time,
            ),
            Tool(
                name="agent_add_preference",
                description="将用户的回答偏好或个人偏好加入向量数据库...",
                parameters={
                    "user_id": {"type": "string", "description": "当前用户的id"},
                    "query": {"type": "string", "description": "需要加入向量数据库的内容"},
                },
                required=["user_id", "query"],
                handler=self.agent_add_preference,
            ),
            Tool(
                name="knowledge_retriever",
                description="使用向量数据库检索基金相关内容...",
                parameters={
                    "query": {"type": "string", "description": "需要进行向量匹配的字段"},
                    "top_k": {"type": "integer", "description": "需要返回的数据条数，一般为5"},
                },
                required=["query"],
                handler=self.knowledge_base.knowledge_retriever,
            ),
            Tool(
                name="get_news",
                description=f"根据平台查询新闻，可选值：{self.platform_list}",
                parameters={"platform": {"type": "string", "description": f"新闻平台，可选值：{self.platform_list}"}},
                required=["platform"],
                handler=self.get_news,
            ),
        ]

    # ── 工具方法（不变）──────────────────
    def search(self, query: str) -> str:       ...
    def get_time(self) -> str:                  ...
    def get_news(self, platform: str) -> str:   ...
    def agent_add_preference(self, user_id: str, query: str) -> str: ...
    def knowledge_retriever(self, query: str, top_k: int = 3) -> str: ...

    # ── 从 self.tools 派生的辅助方法 ──────
    def _get_tool_schemas(self) -> list[dict]:
        return [t.to_openai_schema() for t in self.tools]

    def _get_handler(self, name: str) -> Callable:
        for t in self.tools:
            if t.name == name:
                return t.handler
        raise KeyError(f"LLM 请求了未知工具: {name}")

    async def _safe_execute(self, handler: Callable, params: dict) -> str:
        """工具调用失败时不崩溃，返回错误信息给 LLM"""
        try:
            func = functools.partial(handler, **params)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, func)
            return str(result) if result is not None else "工具执行成功（无返回值）"
        except Exception as e:
            logger.error(f"工具执行失败: {handler.__name__}({params}) → {e}")
            return f"工具调用失败: {type(e).__name__}: {str(e)}"

    # ── Agent 主循环（chat 方法）─────────
    async def chat(self, user_id: str, query: str):
        # ... 省略不变的部分 ...

        # 唯一的变化：获取 schema 和 handler 的方式
        response = self.llm.chat.completions.create(
            tools=self._get_tool_schemas(),    # ← 不再是 _build_tools()
            ...
        )

        # 工具执行部分：
        for func in tool_call_list:
            real_func = self._get_handler(func.function.name)  # ← 不再是 _tool_handlers()[name]
            tool_tasks.append(self._safe_execute(real_func, params))  # ← 不再是裸 run_in_executor
```

> **🔑 关键观察**：`_build_tools()` 和 `_tool_handlers()` 这两个旧方法**彻底消失**。`chat()` 里不再有 `func_mach` 字典。所有工具信息只有一个来源：`self.tools`。

---

## 一、当前问题：为什么需要重构

### 1.1 两套结构，手动同步

打开你现在的 `agent.py`，工具信息散落在两个位置：

| 位置 | 内容 | 行数 |
|------|------|:--:|
| `_build_tools()` | 5 个工具 × 约 15 行 JSON Schema = 75 行 | L92-L158 |
| `_tool_handlers()` | 5 行 `"name": self.method` 映射 | L160-L166 |

这两套结构的**同步完全靠人眼**。你在 schema 里写的 `"name": "search"` 必须和 handler dict 的 key `"search"` 拼写完全一致。写错一个字母，LLM 请求了工具但 Python 抛出 `KeyError`——而且这个错误不会在启动时暴露，只会在**运行时 LLM 恰好调用那个工具时**才炸。

### 1.2 每次迭代都重建

```python
# agent.py 当前代码
for time in range(10):                    # ← 最多 10 轮迭代
    response = self.llm.chat.completions.create(
        tools=self._build_tools(),        # ← 每轮都重建 5 个 dict 的列表
        ...
    )
    # ...
    real_func = self._tool_handlers()[name]  # ← 每轮都重建 dict，每个 tool 调用都重建
```

如果 LLM 一轮对话做了 3 轮 tool-calling，`_build_tools()` 调用 3 次，`_tool_handlers()` 调用 N 次（N = 工具调用总数）。功能上没问题，但暴露了一个设计信号：**你没有一个"工具注册表"的概念**，你每次用到工具时都在重新发明它。

### 1.3 工具执行无保护

```python
# agent.py:193-194
construct_func = functools.partial(real_func, **params)
tool_tasks.append(loop.run_in_executor(None, construct_func))
```

如果 Tavily API 挂了、新闻 API 返回 502、ChromaDB 磁盘满了——异常直接穿透到 FastAPI 的 SSE 流，客户端收到 500 Internal Server Error。LLM 收不到任何反馈，对话直接中断。

---

## 二、核心知识点：`@dataclass`

你目前的工具信息散落在三种结构里：方法体、dict（schema）、dict（handler 映射）。dataclass 是把这三种信息焊成一个对象的工具。

### 最小示例

```python
from dataclasses import dataclass
from typing import Callable

@dataclass
class Tool:
    name: str                    # 工具名
    description: str             # 给 LLM 看的描述
    parameters: dict             # JSON Schema 的 properties 部分
    required: list[str]          # JSON Schema 的 required 部分
    handler: Callable            # 实际执行的方法

# 用法：
def my_search(query: str) -> str:
    return f"搜索结果：关于 {query}"

tool = Tool(
    name="search",
    description="搜索互联网",
    parameters={"query": {"type": "string", "description": "关键词"}},
    required=["query"],
    handler=my_search
)

tool.handler(query="天气")  # → "搜索结果：关于 天气"
```

`@dataclass` 是 Python 3.7+ 的装饰器，自动生成 `__init__`、`__repr__` 等方法。和 JS 的 `class Tool { constructor(name, handler) { this.name = name } }` 等价，但不需要手写 constructor。

### ⚠️ Python 经典陷阱：可变默认参数

```python
# ❌ 错误写法 —— 所有 Tool 实例共享同一个 list！
@dataclass
class Tool:
    required: list[str] = []    # 这个 [] 在类定义时只创建一次

# ✅ 正确写法
from dataclasses import field

@dataclass
class Tool:
    required: list[str] = field(default_factory=list)  # 每个实例独立创建
```

---

## 三、分步实施

每一步都是**可运行、可验证**的中间态。不要跳步。

---

### 步骤 1：写 `Tool` dataclass

**改什么**：`agent.py` 顶部，import 之后，`class FundAgent` 之前，加约 25 行。

**改造前**：
```python
from memory import AgentMemory
from knowledge.knowledge_base import KnowledgeInit
from openai import OpenAI
# ... 其他 import ...

logger = logging.getLogger("agent")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

class FundAgent:        # ← 直接进入 FundAgent
```

**改造后**：
```python
from memory import AgentMemory
from knowledge.knowledge_base import KnowledgeInit
from openai import OpenAI
# ... 其他 import ...
from dataclasses import dataclass, field     # ← 新增
from typing import Callable                   # ← 新增

logger = logging.getLogger("agent")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")


# ═══════════════════════════════════════════════════
# 新增：Tool 数据类
# ═══════════════════════════════════════════════════
@dataclass
class Tool:
    name: str
    description: str
    parameters: dict          # properties 部分，不含外层 type/required 包装
    handler: Callable
    required: list[str] = field(default_factory=list)

    def to_openai_schema(self) -> dict:
        """生成 OpenAI Function Calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }


class FundAgent:        # ← 然后才是 FundAgent
```

**验证**：在项目根目录运行：

```bash
python -c "
from agent import Tool
t = Tool(name='test', description='测试', parameters={'x': {'type': 'string'}}, handler=print, required=['x'])
import json
print(json.dumps(t.to_openai_schema(), indent=2, ensure_ascii=False))
"
```

**预期输出**：
```json
{
  "type": "function",
  "function": {
    "name": "test",
    "description": "测试",
    "parameters": {
      "type": "object",
      "properties": {
        "x": { "type": "string" }
      },
      "required": ["x"]
    }
  }
}
```

---

### 步骤 2：在 `__init__` 中注册 `self.tools`

**改什么**：`FundAgent.__init__` 末尾加 `self.tools = [...]`。

> **关键原则**：旧代码 **一行都不删**。`_build_tools()` 和 `_tool_handlers()` 原样保留。两边并存，你才能验证新旧输出一致。

**改造前**（`__init__` 结尾）：
```python
        self.platform_list = self._load_platforms()
        # __init__ 结束，没有 self.tools
```

**改造后**：
```python
        self.platform_list = self._load_platforms()

        # ── 工具注册表（新增）──────────────────
        self.tools: list[Tool] = [
            Tool(
                name="search",
                description="使用搜索引擎检索信息",
                parameters={
                    "query": {"type": "string", "description": "搜索关键词"},
                },
                required=["query"],
                handler=self.search,
            ),
            Tool(
                name="get_time",
                description="获取当前日期",
                parameters={},
                handler=self.get_time,
            ),
            Tool(
                name="agent_add_preference",
                description="将用户的回答偏好或个人偏好加入向量数据库，以便于后续生成更客制化的回答",
                parameters={
                    "user_id": {"type": "string", "description": "当前用户的id"},
                    "query": {"type": "string", "description": "需要加入向量数据库的内容"},
                },
                required=["user_id", "query"],
                handler=self.agent_add_preference,
            ),
            Tool(
                name="knowledge_retriever",
                description="使用向量数据库检索基金相关内容，向量数据库中是各部门的财报等各种与基金股票相关的金融研报，若返回值中有你认为相关的内容，可以通过url进行搜索",
                parameters={
                    "query": {"type": "string", "description": "需要进行向量匹配的字段"},
                    "top_k": {"type": "integer", "description": "需要返回的数据条数，一般为5，必要时可进行调整"},
                },
                required=["query"],
                handler=self.knowledge_base.knowledge_retriever,
            ),
            Tool(
                name="get_news",
                description=f"根据平台查询新闻，该接口每半小时更新一次，新闻情况会影响基金的动向，当你需要了解实时性新闻时，调用该方法",
                parameters={
                    "platform": {"type": "string", "description": f"新闻平台，可选值：{self.platform_list}"},
                },
                required=["platform"],
                handler=self.get_news,
            ),
        ]
```

**验证**：运行应用，确认功能不受影响（旧代码还在用，新代码只是"搁在那儿"）。发一条对话测试。

---

### 步骤 3：用 `self.tools` 重写 `_build_tools()`

**改什么**：把 `_build_tools()` 的 60 行硬编码 dict 替换为一行列表推导式。

**改造前**：
```python
    def _build_tools(self) -> list[dict]:
        """生成 OpenAI tools 参数"""
        return [{
            "type": "function",
            "function": {
                "name": "search",
                "description": "使用搜索引擎检索信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"}
                    },
                    "required": ["query"]
                }
            }
        }, {
            # ... 60 行 ...
        }]
```

**改造后**：
```python
    def _build_tools(self) -> list[dict]:
        """生成 OpenAI tools 参数"""
        return [t.to_openai_schema() for t in self.tools]
```

**验证**：在 Python 交互环境中对比新旧输出：

```bash
python -c "
import json
from agent import FundAgent
agent = FundAgent()
# 新旧两种方式都跑一遍，对比
old = agent._build_tools_old() if hasattr(agent, '_build_tools_old') else None
new = agent._build_tools()
print(json.dumps(new, indent=2, ensure_ascii=False))
"
```

> 如果担心改坏，先重命名旧方法为 `_build_tools_old()`，新方法叫 `_build_tools()`，验证完再删旧的。

---

### 步骤 4：加 `_get_handler()` 并用它替换 `_tool_handlers()[name]`

**改什么**：新增 `_get_handler()` 方法，`chat()` 里改一处调用。

**新增方法**（放在 `_build_tools` 旁边）：
```python
    def _get_handler(self, name: str) -> Callable:
        """按名称查找 handler"""
        for t in self.tools:
            if t.name == name:
                return t.handler
        raise KeyError(f"LLM 请求了未知工具: {name}")
```

**`chat()` 里改一行**：

```python
# 改造前（agent.py 约第 190 行）：
real_func = self._tool_handlers()[func_setting.name]

# 改造后：
real_func = self._get_handler(func_setting.name)
```

**验证**：发一条"帮我搜一下今天的财经新闻"，确认 tool-calling 仍正常工作。

---

### 步骤 5：删掉 `_build_tools()` 和 `_tool_handlers()` 的旧实现

**改什么**：删除这两个旧方法。

> 此时 `_build_tools()` 已被步骤 3 重写为一句话的推导式（保留），`_tool_handlers()` 已经没人在调用了（删除）。

**改造前**：
```python
    def _build_tools(self) -> list[dict]:
        return [t.to_openai_schema() for t in self.tools]   # ← 步骤3改完的样子，保留

    def _tool_handlers(self) -> dict:                        # ← 删掉整个方法
        return {
            "search": self.search,
            ...
        }
```

**改造后**：
```python
    def _build_tools(self) -> list[dict]:
        return [t.to_openai_schema() for t in self.tools]
    # _tool_handlers 消失
```

**验证**：搜索 `_tool_handlers` 确保全文件无残留引用（注释除外）。

```bash
grep -n "_tool_handlers" agent.py
# 应该无输出，或者只有步骤注释里的文字
```

---

### 步骤 6：加 `_safe_execute()` 错误保护

**改什么**：新增 `_safe_execute()` 方法，`chat()` 的工具执行部分改用它。

**新增方法**：
```python
    async def _safe_execute(self, handler: Callable, params: dict) -> str:
        """包装工具执行 —— 失败时返回错误信息而非崩溃"""
        try:
            func = functools.partial(handler, **params)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, func)
            return str(result) if result is not None else "工具执行成功（无返回值）"
        except Exception as e:
            logger.error(f"工具执行失败: {handler.__name__}({params}) → {e}")
            return f"工具调用失败: {type(e).__name__}: {str(e)}"
```

**`chat()` 里改两行**：

```python
# 改造前（agent.py 约第 193 行）：
construct_func = functools.partial(real_func, **params)
tool_tasks.append(loop.run_in_executor(None, construct_func))

# 改造后：
tool_tasks.append(self._safe_execute(real_func, params))
```

**验证**：正常情况下的对话应不受影响。模拟失败场景：临时把 `TAVILY_API_KEY` 改成错误的值，发一条搜索类问题，观察 LLM 是否收到 `"工具调用失败: AuthenticationError: ..."` 而不是 500。

---

### 步骤 7：修复 `chunk_world.py` 的 `count` 累加

**改什么**：`knowledge/chunk_world.py` 一处。

**改造前**：
```python
# chunk_world.py 约第 56 行
count += 100
```

**改造后**：
```python
count += len(batch_chunks["ids"])
```

**验证**：看 logger 输出的 `加载知识库 X/25000` 中的 X 是否等于实际已加载条数。

---

## 四、步骤依赖关系

```
步骤1 (Tool dataclass)
  ↓
步骤2 (self.tools 注册)     ← 步骤2-4 可以并行理解，但实施必须顺序
  ↓
步骤3 (重写 _build_tools)   ← 从这里开始，旧代码的"外皮"还在但"内脏"已替换
  ↓
步骤4 (加 _get_handler)     ← 改完这步，chat() 不再依赖 _tool_handlers()
  ↓
步骤5 (删除旧方法)          ← 收尾：删掉不再使用的 _tool_handlers()
  ↓
步骤6 (_safe_execute)       ← 独立功能，也可以在第 4 步和第 5 步之间做
  ↓
步骤7 (count 修复)          ← 独立，不依赖前面任何步骤
```

---

## 五、改造前后完整对比

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| **工具定义位置** | `_build_tools()` + `_tool_handlers()` + 方法体，共 3 处 | `self.tools` 列表，1 处 |
| **加新工具的操作** | ①写方法 ②在 `_build_tools` 加 ~15 行 schema ③在 `_tool_handlers` 加映射 | 在 `self.tools` 加一个 `Tool(...)` 构造 |
| **Schema 生成** | 手写 dict，和 handler 映射靠人眼保持同步 | `t.to_openai_schema()` 自动生成，名称来自 `t.name` |
| **性能** | 每轮迭代重建 list + dict | `self.tools` 在 `__init__` 创建一次，`_get_tool_schemas()` 只做轻量推导 |
| **错误处理** | 工具抛异常 → 500 + traceback，LLM 不知情 | `_safe_execute` 捕获 → LLM 收到 `"工具调用失败: XXXError: ..."` |
| **count 累加** | `count += 100` 硬编码 | `count += len(batch_chunks["ids"])` |

---

## 六、自我检查清单

完成后逐条自检：

- [ ] `grep "_tool_handlers" agent.py` 无结果
- [ ] `grep "func_mach" agent.py` 无结果
- [ ] 新建一个 Tool 只需要在 `self.tools` 列表加一个 `Tool(...)`，不需要碰任何其他地方
- [ ] `_get_handler("不存在的工具")` 抛出 `KeyError("LLM 请求了未知工具: 不存在的工具")`
- [ ] `chunk_world.py` 中 `count` 的累加用的是 `len(batch_chunks["ids"])` 而非 `+= 100`
- [ ] 发一条真实对话请求，tool-calling 正常工作
