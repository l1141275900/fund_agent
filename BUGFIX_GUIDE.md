# Bug 修复引导文档

> **阅读方式**：每个 Bug 包含"现象 → 根因 → 涉及的知识点 → 修复思路"四步。不要直接看修复思路，先自己尝试。

---

## Bug #1（重新审定）：`agent_add_preference` 创建了新 `AgentMemory` 实例

### 你的质疑

> "既然它们写入了不同的 client，为什么它每次启动时都能读到我之前写入的偏好？"

**你是对的，我之前夸大了这个 Bug 的严重程度。** 这个 Bug 不会导致数据丢失，但它是一个需要修正的设计问题。下面详细解释。

### 为什么"写入不同 client"却仍然能读到？

关键在于 ChromaDB 的 `PersistentClient` 的工作原理：

```python
# app.py —— 应用启动时创建（app 级别）
memory = AgentMemory()                    # persist_path 默认 "./memory"

# memory.py —— LLM 调用 tool 时创建（函数级别）
def agent_add_preference(user_id, query):
    memory = AgentMemory()                # persist_path 默认 "./memory"
    memory.add_preference(user_id, query)
```

**两个 `AgentMemory()` 都使用默认参数 `persist_path="./memory"`**，它们虽然在内存中是两个不同的 Python 对象（两个不同的 client 连接），但它们操作的是**磁盘上同一个文件夹**里的同一份数据库文件。

类比理解：

```
┌─────────────────────────────────────┐
│           你的硬盘                    │
│  ./memory/                           │
│  ├── chroma.sqlite3    ← 真正的数据   │
│  └── .../              ← 向量索引     │
└─────────────────────────────────────┘
       ▲                    ▲
       │                    │
  ┌────┴────┐         ┌────┴────┐
  │ Client A │         │ Client B │
  │(app 级别)│         │(tool 内) │
  └─────────┘         └─────────┘
```

两个 client 就像两个不同的遥控器，但控制的是同一台电视。所以：

- `agent_add_preference` 写入 → 数据落盘到 `./memory/`
- `memory.preference_retriever()` 从 `./memory/` 读取 → **能看到写入的数据** ✅

### 那这还算 Bug 吗？

**算，但降级为设计缺陷。** 它目前"碰巧能工作"是因为两个地方用了相同的默认路径，但存在三个隐患：

| 隐患 | 说明 |
|------|------|
| **性能浪费** | 每次 LLM 调用 `agent_add_preference` 工具，都会新建一个 `PersistentClient` + 一个 `SentenceTransformerEmbeddingFunction`（嵌入模型挺大的）。相当于每次写一条记录就"重启一次数据库连接"。 |
| **并发风险** | 两个 client 同时操作同一个 SQLite 文件（ChromaDB 底层是 SQLite），可能触发 `database is locked` 错误。 |
| **脆弱性** | 如果将来有人改了 `app.py` 里的路径（比如 `AgentMemory("./prod_memory")`），但忘了改 `agent_add_preference` 里的路径，数据就会真的写到两个不同的数据库，bug 从"设计缺陷"升级为"数据丢失"。 |

### 涉及的知识点：闭包（Closure）

你提到不理解"需要通过闭包或参数拿到 app 级别的 memory"，下面用最小示例解释。

**闭包 = 函数"记住"了它出生时外面的变量**

```python
def outer():
    x = 10          # outer 的局部变量

    def inner():    # inner 定义在 outer 里面
        print(x)    # inner 可以访问 outer 的 x —— 这就是闭包

    return inner

f = outer()
f()  # 输出 10  ← inner 记住了 x=10，即使 outer 已经执行完毕
```

应用到你的项目：

```python
# ❌ 现在：agent_add_preference 是全局函数，拿不到 create_response 里的 memory
def agent_add_preference(user_id, query):
    memory = AgentMemory()   # 只能自己 new 一个
    ...

async def create_response(user_id, query, memory, kb):
    # memory 在这里，但 agent_add_preference 够不着
    func_mach = {"agent_add_preference": agent_add_preference, ...}

# ✅ 修复后：把 agent_add_preference 定义在 create_response 里面
async def create_response(user_id, query, memory, kb):

    def agent_add_preference(user_id, query):   # ← 定义在内部
        memory.add_preference(user_id, query)    # ← 直接用外层的 memory！
        return "成功"

    func_mach = {"agent_add_preference": agent_add_preference, ...}
```

`agent_add_preference` 定义在 `create_response` 内部后，它就能"看见"外层传入的 `memory` 参数——不需要自己 `new AgentMemory()`。

这就是**闭包**：内部函数捕获了外部函数的变量。

### 修复方案对比

解决这个问题的本质是：**让工具函数拿到 app 级别的 `memory` 实例**。有三种方案：

| | 方案 A：闭包 | 方案 B：类封装（推荐） | 方案 C：Tool 协议 |
|---|---|---|---|
| 思路 | 把工具函数嵌套在 `create_response` 内部 | 所有工具变成 `FundAgent` 类的方法，`self.memory` 统一访问 | 每个工具是独立类，实现统一接口 |
| `memory` 从哪来 | 闭包捕获外层参数 | 构造函数注入 → `self.memory` | 构造函数注入 → `self.memory` |
| 改动量 | 小（只动 main.py） | 中（新建 agent.py，改 3-4 个文件） | 大（每个工具一个文件） |
| 可测试性 | 差（函数嵌套无法单独测试） | 好（`FundAgent(mock_memory)` 即测） | 最好 |
| 适合当前项目 | 临时包扎 | ✅ 最佳匹配 | ❌ 杀鸡用牛刀 |

### 为什么选方案 B

1. **你的项目已经到了"函数臃肿"的拐点。** `create_response` 已经 180 行，里面混杂了 5 个工具的 JSON Schema、工具注册映射、Agent 循环、流式处理——这是典型的"一个函数干了所有事"
2. **方案 B 不是"修一个 Bug"，而是"推进一步架构"**——从面向函数脚本升级到面向对象结构，这是你下一个学习阶段的核心技能
3. **不影响现有功能。** 本质是搬家：把散落各处的逻辑搬到类的方法里，外部行为不变
4. **你理解 JS 的 class**——Python 的类只会更简洁，没有 `this` 绑定的各种坑

### 方案 B 详细设计：`FundAgent` 类

#### 改造前 vs 改造后

```
改造前：
  main.py  ─── 180行巨石函数 create_response + 散落四处的工具函数
  app.py   ─── lifespan 中创建 memory + kb
  router   ─── 直接调用 create_response()

改造后：
  agent.py     ─── FundAgent 类（新建，~150行）
                    ├── __init__():      接收 memory, kb，初始化 OpenAI client
                    ├── _build_tools():  返回 tools JSON Schema 列表
                    ├── _tool_handlers(): 返回 {"工具名": self.方法} 映射
                    ├── chat():          原 create_response 逻辑
                    ├── search():        工具方法
                    ├── get_time():      工具方法
                    ├── get_news():      工具方法
                    ├── agent_add_preference(): self.memory ← 一次性解决 Bug #1
                    └── knowledge_retriever():     self.kb      ← 同上
  main.py     ─── 仅保留 AgentMemory 类（或也移走）
  app.py      ─── lifespan: app.state.agent = FundAgent(memory, kb)
  router      ─── agent.chat() 替代 create_response()
```

#### 核心代码结构

```python
# agent.py（新建文件）
import functools
import hashlib
import json
import os
from datetime import datetime
import asyncio

from openai import OpenAI
from tavily import TavilyClient
import httpx

from schema.output import format_output


class FundAgent:
    """基金分析 Agent —— 所有工具和对话逻辑封装为类"""

    def __init__(self, memory, kb):
        # 依赖注入：构造时一次性注入，后续所有方法通过 self 访问
        self.memory = memory
        self.kb = kb

        # OpenAI 客户端
        self.llm = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )

        # 外部 API 客户端（Tavily 复用，不再每次 search 时 new）
        self.tavily_client = TavilyClient(os.getenv("TAVILY_API_KEY"))

        # 平台列表（从文件读取，只读一次）
        self.platform_list = self._load_platforms()

    # ── 工具方法 ──────────────────────────────────

    def search(self, query: str) -> str:
        """搜索引擎检索"""
        response = self.tavily_client.search(
            query=query,
            include_answer="basic",
            search_depth="advanced",
        )
        return response["answer"]

    def get_time(self) -> str:
        """获取当前时间"""
        return str(datetime.now())

    def get_news(self, platform: str) -> str:
        """根据平台查询新闻"""
        with httpx.Client(follow_redirects=True) as client:
            response = client.get(
                "https://orz.ai/api/v1/dailynews",
                params={"platform": platform},
            )
            data = response.json()                              # ← 只调用一次！
            status = data.get("status", -1)                     # ← 修 Bug #2
            if status == "200":
                return data["data"]
            return "搜索失败，请强调提醒用户此次搜索失败情况"

    def agent_add_preference(self, user_id: str, query: str) -> str:
        """将用户偏好写入向量数据库"""
        self.memory.add_preference(user_id, query)              # ← 修 Bug #1
        return "成功"

    def knowledge_retriever(self, query: str, top_k: int = 3) -> str:
        """检索基金知识库"""
        return self.kb.knowledge_retriever(query, top_k)

    # ── 内部方法 ──────────────────────────────────

    def _load_platforms(self) -> list[str]:
        """从 new_platform.txt 提取平台代码"""
        platforms = []
        with open("new_platform.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # 只提取以数字序号开头的行（即表格数据行）
                parts = line.split("\t")
                if len(parts) >= 3 and parts[0].strip().isdigit():
                    platforms.append(parts[2].strip())
        return platforms

    def _build_tools(self) -> list[dict]:
        """生成 OpenAI tools 参数"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "使用搜索引擎检索信息",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "搜索关键词"}
                        },
                        "required": ["query"],
                    },
                },
            },
            # ... 其余 4 个工具定义，结构不变
        ]

    def _tool_handlers(self) -> dict:
        """返回 '工具名 → 方法' 的映射，替代原来的 func_mach 字典"""
        return {
            "search": self.search,
            "get_time": self.get_time,
            "get_news": self.get_news,
            "agent_add_preference": self.agent_add_preference,
            "knowledge_retriever": self.knowledge_retriever,
        }

    # ── Agent 主循环 ──────────────────────────────

    async def chat(self, user_id: str, query: str):
        """Agent 对话入口（原 create_response 逻辑）"""
        tools = self._build_tools()
        func_mach = self._tool_handlers()

        messages_list = [{"role": "user", "content": query}]
        conversation_history = self.memory.conversation_retriever(user_id, query)
        query_knowledge = self.kb.knowledge_retriever(query=query)

        for iteration in range(10):
            user_preference = self.memory.preference_retriever(user_id, query)

            response = self.llm.chat.completions.create(
                model="deepseek-v4-flash",
                messages=[{
                    "role": "system",
                    "content": f"""... system prompt 不变 ..."""
                }, *messages_list],
                tools=tools,
                tool_choice="auto",
                stream=True,
            )

            # ── 流式处理（逻辑不变）─────────────
            full_content = ""
            tool_call_dict = {}
            for chunk in response:
                message = chunk.choices[0].delta

                if message.content:
                    full_content += message.content
                    yield format_output(json.dumps({
                        "content": message.content,
                        "reasoning_content": None,
                        "tool_calling": None,
                    }))

                if hasattr(message, "reasoning_content") and message.reasoning_content:
                    yield format_output(json.dumps({
                        "content": None,
                        "reasoning_content": message.reasoning_content,
                        "tool_calling": None,
                    }))

                if message.tool_calls:
                    for tool_item in message.tool_calls:
                        idx = tool_item.index
                        if idx not in tool_call_dict:
                            tool_call_dict[idx] = tool_item
                        else:
                            tool_call_dict[idx].function.arguments += tool_item.function.arguments

            tool_call_list = list(tool_call_dict.values())

            if not tool_call_list or full_content.startswith("[finish]"):
                self.memory.add_conversation(user_id, query, str(messages_list[1:]))
                break

            messages_list.append({"role": "assistant", "content": full_content or ""})

            if tool_call_list:
                loop = asyncio.get_event_loop()
                tool_tasks = []
                messages_list[-1]["tool_calls"] = tool_call_list

                for func in tool_call_list:
                    func_setting = func.function
                    real_func = func_mach[func_setting.name]
                    params = json.loads(func_setting.arguments)

                    yield format_output(json.dumps({
                        "content": None,
                        "reasoning_content": None,
                        "tool_calling": f"{func_setting.name}({func_setting.arguments})",
                    }))

                    construct_func = functools.partial(real_func, **params)
                    tool_tasks.append(loop.run_in_executor(None, construct_func))

                results = await asyncio.gather(*tool_tasks)
                for i, item in enumerate(results):
                    messages_list.append({
                        "role": "tool",
                        "tool_call_id": tool_call_list[i].id,
                        "content": item,
                    })
```

#### 配套改造：`app.py`

```python
# app.py —— 原来
app.state.memory = memory
app.state.knowledge_base = kb

# app.py —— 改造后
from agent import FundAgent

app.state.agent = FundAgent(memory, kb)
# memory 和 kb 不再需要暴露给 router，都封装在 agent 内部了
```

#### 配套改造：`router.py`

```python
# router.py —— 原来
@router.post('/query')
async def chat(res: ChatRequest, request: Request):
    memory = request.app.state.memory
    kb = request.app.state.knowledge_base
    return StreamingResponse(
        content=create_response(res.user_id, res.query, memory, kb),
        media_type="text/event-stream"
    )

# router.py —— 改造后
@router.post('/query')
async def chat(res: ChatRequest, request: Request):
    agent = request.app.state.agent
    return StreamingResponse(
        content=agent.chat(res.user_id, res.query),   # ← 不再需要传 memory, kb
        media_type="text/event-stream"
    )
```

### 改造后，Bug #1 如何被解决？

```python
# ❌ 改造前：函数是独立的，拿不到 memory
def agent_add_preference(user_id, query):
    memory = AgentMemory()           # ← 只能自己 new
    memory.add_preference(user_id, query)

# ✅ 改造后：方法是类的一部分，self.memory 由构造函数注入
class FundAgent:
    def __init__(self, memory, kb):
        self.memory = memory         # ← 一次性注入

    def agent_add_preference(self, user_id, query):
        self.memory.add_preference(user_id, query)   # ← 直接用
```

**依赖注入的本质**：对象的依赖不从内部创建（`AgentMemory()`），而是从外部传入（`FundAgent(memory)`），对象只负责使用。这和 JS 里 `class Foo { constructor(db) { this.db = db } }` 是一样的。

---



## Bug #2：`get_news` 永远返回"搜索失败"

### 现象

不论什么平台，新闻查询总是返回失败。

### 根因

核心问题在 `getattr` 的误用：

```python
def get_news(platform: str):
    with httpx.Client(follow_redirects=True) as client:
        response = client.get("https://orz.ai/api/v1/dailynews", params={"platform": platform})
        res = getattr(response.json(), "status", -1)   # ← 这里
        if res == '200':
            return response.json()["data"]
        else:
            return "搜索失败，请强调提醒用户此次搜索失败情况"
```

### 知识点：`getattr` vs dict 取值

Python 里，**对象的属性**和**字典的键**是两套不同的体系：

```python
data = {"status": "200", "name": "张三"}

# ✅ 字典取值：用方括号或 .get()
data["status"]         # → "200"
data.get("status", -1) # → "200"

# ❌ getattr：用来取对象的属性，对 dict 无效
getattr(data, "status", -1)  # → -1  （因为 dict 没有 status 这个属性！）
```

`getattr(obj, name, default)` 的意思是"取对象 `obj` 的 **属性** `name`"，不是"取字典的键"。`response.json()` 返回的是一个 `dict`，dict 对象没有名为 `status` 的属性，所以 `getattr` 永远返回默认值 `-1`。

`-1 == '200'` 永远是 `False` → 永远走 `else` 分支 → 永远返回失败。

### 附加问题：多次调用 `.json()`

代码中 `response.json()` 被调用了 3 次：

```python
logger.info(f"新闻搜索结果：{response.json()}")   # 第1次
res = getattr(response.json(), "status", -1)      # 第2次
return response.json()["data"]                    # 第3次
```

虽然 httpx 缓存了解析结果、多次调用不会重复请求网络，但这是坏习惯。应该调用一次，存到变量里。

### 修复思路

1. `response.json()` 只调用一次，存到变量 `data`
2. 用 `data.get("status", -1)` 替换 `getattr(response.json(), "status", -1)`
3. 后续使用 `data["data"]` 而不是第三次调用 `.json()`

---

## Bug #3：`platform_list` 带 `\n` 换行符

### 现象

LLM 调用 `get_news` 时传入的平台代码实际上带了换行符，比如 `"baidu\n"` 而不是 `"baidu"`，导致 API 匹配不到平台。

### 根因

```python
# env.py
with open("new_platform.txt", "r", encoding="utf-8") as f:
    platform_list = f.readlines()   # ← readlines 保留每行末尾的 \n
```

### 知识点：`readlines()` vs `read().splitlines()`

```python
# new_platform.txt 内容（示意）：
# baidu
# weibo

# readlines() 的结果：
["baidu\n", "weibo\n"]           # ← 每行带 \n

# 你实际想要的是：
["baidu", "weibo"]
```

| 方法 | 结果 |
|------|------|
| `f.readlines()` | `["baidu\n", "weibo\n"]` |
| `f.read().splitlines()` | `["baidu", "weibo"]` |
| `[line.strip() for line in f]` | `["baidu", "weibo"]` |

而且 `new_platform.txt` 的前几行是表头和分隔符：

```
我们目前支持以下平台的热点内容获取：

序号	平台名称	平台代码	内容类型	状态
1	百度热搜	baidu	社会热点、娱乐、事件	✅
```

`readlines()` 会把"我们目前支持以下平台的热点内容获取："和"序号	平台名称..."这些非平台代码的行也读进去。所以 `platform_list` 里实际混入了表头文字和空行，比如：

```python
["我们目前支持以下平台的热点内容获取：\n", "\n", "序号\t平台名称\t平台代码...\n", ...]
```

这个列表被拼进 LLM 的 tool description 里（`f"新闻平台，可选值：{platform_list}"`），LLM 看到的可选值会有大量噪音。

### 修复思路

不需要 `env.py` 在模块级读取文件。更好的做法：

1. 写一个函数 `get_platform_list()` 按需读取
2. 只提取表格行中第 3 列（平台代码），跳过表头
3. 对每行做 `strip()` 去掉换行符

或者更简单：把平台代码硬编码为一个 Python list，因为这份数据不会频繁变动。

---

## Bug #4：`chunk_world.py` 知识库最后一批数据可能丢失

### 现象

当数据量刚好达到 `MAX_DATA_SIZE`（200 条）时，最后一个不满 100 条的批次被丢弃。

### 根因

```python
count = 0
for line in f:
    # ... 把数据加入 batch_chunks ...

    if len(batch_chunks["ids"]) >= batch_size:    # batch_size = 100
        await kb.add_knowledge(batch_chunks)       # 提交这一批
        batch_chunks = {"ids": [], ...}            # 重置为空
        count += 100                               # ← 假设每批恰好 100 条
        if count >= MAX_DATA_SIZE:                 # MAX_DATA_SIZE = 200
            break                                  # ← 直接跳出！
```

一步一步追踪（假设文件有 250 条数据）：

| 迭代 | 累积条数 | 触发提交？ | count | 发生了什么 |
|------|---------|-----------|-------|-----------|
| 1-100 | 100 | ✅ 提交第 1 批 | 100 | `100 >= 200`? No，继续 |
| 101-200 | 100 | ✅ 提交第 2 批 | 200 | `200 >= 200`? **Yes，break！** |

此时 `batch_chunks` 刚被重置为空 dict（第 200 条在第 2 批里已经被提交了），所以 break 时没有未提交的数据——**碰巧没丢**。

但如果 `MAX_DATA_SIZE = 250`：

| 迭代 | 累积条数 | 触发提交？ | count | 发生了什么 |
|------|---------|-----------|-------|-----------|
| 1-100 | 100 | ✅ 提交第 1 批 | 100 | 继续 |
| 101-200 | 100 | ✅ 提交第 2 批 | 200 | 继续 |
| 201-250 | 50（不满） | ❌ 未触发提交 | 200 | 循环结束，**50 条数据在 batch_chunks 里，未被提交！** |

### 知识点：循环结束后的收尾（cleanup）

这是一个典型的"循环内攒批次 + 循环外收尾"模式：

```python
# ✅ 正确的批次处理模式
batch = []
for item in items:
    batch.append(item)
    if len(batch) >= batch_size:
        process(batch)       # 提交满的批次
        batch = []           # 重置
        if reached_limit:
            break

# 👇 关键：循环结束后，处理剩下的不满一批的数据
if batch:
    process(batch)
```

你的代码缺少的就是最后这个 `if batch: process(batch)`。

### 修复思路

1. 在 `break` 之前检查当前 `batch_chunks` 是否有未提交的数据，如果有就先提交再 break
2. 在 `for` 循环结束后（正常结束，非 break）也检查一次 `batch_chunks`
3. `count` 的更新应该用实际提交的条数，而不是 `+= 100` 硬编码

---

## 修复建议顺序

```
Bug #3（最简单，改一行） → Bug #2（改一处逻辑） → Bug #1（理解闭包 + 移动函数） → Bug #4（循环收尾）
```

建议先从 #3 开始，获得快速的正反馈，再逐步挑战更复杂的。

---

## 自我检查清单

修复完每个 Bug 后，问自己：

- Bug #3：`print(platform_list)` 打印出来还有 `\n` 和表头文字吗？
- Bug #2：`get_news("baidu")` 还能复现"搜索失败"吗？
- Bug #1：`agent_add_preference` 里还有 `memory = AgentMemory()` 这行吗？
- Bug #4：如果 `MAX_DATA_SIZE = 5` 且 `batch_size = 3`，最后两条数据能被提交吗？
