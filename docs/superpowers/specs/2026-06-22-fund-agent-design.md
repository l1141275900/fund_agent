# 基金分析 Agent 设计文档

## 项目定位

面向普通基民的智能基金分析助手。用户无需懂财经术语，用自然语言即可：
- 诊断自己的基金持仓是否合理
- 获取每日关键资讯摘要
- 询问某只或某类基金的情况

同时，这是你的 Agent 开发学习项目，架构设计兼顾**学习价值**和**简历展示**。

---

## 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                      FastAPI 入口                        │
│         lifespan: 启动时加载双引擎 + 定时调度器              │
├─────────────────────────────────────────────────────────┤
│                                                         │
│   ┌──────────────┐                   ┌──────────────┐   │
│   │  语义引擎      │                   │  数据引擎     │   │
│   │  ChromaDB     │                   │  SQLite      │   │
│   │  研报/资讯向量  │                   │  基金信息/净值 │   │
│   └──────┬───────┘                   └──────┬───────┘   │
│          │                                  │           │
│   ┌──────┴──────────────────────────────────┴───────┐   │
│   │              Agent 路由层                        │   │
│   │      根据 query 类型分发到对应引擎                 │   │
│   └──────────────────────┬────────────────────────┘   │
│                          │                            │
│   ┌──────────────────────┴────────────────────────┐   │
│   │               LLM 合成层                       │   │
│   │       DeepSeek 结合检索结果生成自然语言回答       │   │
│   └──────────────────────┬────────────────────────┘   │
│                          │                            │
├──────────────────────────┴────────────────────────────┤
│                     API 层                             │
│   POST /chat         对话入口                          │
│   POST /portfolio    持仓诊断                          │
│   GET  /digest       每日资讯摘要                      │
│   GET  /search       知识库检索（调试用）               │
└────────────────────────────────────────────────────────┘
```

### 为什么需要双引擎？

这是本架构最核心的设计决策。你需要理解两种"数据查询"的根本区别：

| | 语义检索（ChromaDB） | 精确查询（SQLite） |
|---|---|---|
| 典型问题 | "这只基金投资什么方向？" | "这只基金近3月涨了多少？" |
| 查询方式 | 把问题转成向量，找相似文本 | 按代码、日期精确筛选、排序 |
| 答案来源 | 研报片段、资讯文章 | 净值数字、持仓比例 |
| 如果只用对方 | 查不出精确数字，可能幻觉编造 | 无法理解"投资方向"这种语义问题 |

**一句话：** 向量库负责"理解"，SQLite 负责"计算"。Agent 的价值在于把两者结合。

---

## 子系统设计

### 1. 数据引擎（SQLite + Text2SQL）

#### 1.1 为什么选 SQLite？

SQLite 和 ChromaDB 有一个共同特点：**零配置、单文件存储、不需要额外服务进程**。你的项目拷到任何机器上，安装依赖就能跑，不需要装 MySQL 或启动 Docker。

> **讲解：SQLite 是什么？**
> SQLite 是一个嵌入式关系型数据库。它不像 MySQL 那样需要单独的服务进程——SQLite 就是一个 C 库，直接对 `.db` 文件读写。Python 标准库自带 `sqlite3` 模块，无需额外安装。

#### 1.2 数据表设计

**funds 表 — 基金基础信息**

```sql
CREATE TABLE funds (
    code        TEXT PRIMARY KEY,    -- 基金代码，如 "000001"
    name        TEXT NOT NULL,       -- 基金名称
    fund_type   TEXT,                -- 类型：股票型/混合型/债券型/货币型
    manager     TEXT,                -- 基金经理
    company     TEXT,                -- 基金公司
    scale       REAL,                -- 规模（亿元）
    fee_rate    REAL,                -- 管理费率（%）
    created_at  TEXT                 -- 成立日期
);
```

**fund_nav 表 — 净值历史**

```sql
CREATE TABLE fund_nav (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_code   TEXT NOT NULL,       -- 基金代码
    nav_date    TEXT NOT NULL,       -- 净值日期
    unit_nav    REAL,                -- 单位净值
    acc_nav     REAL,                -- 累计净值
    daily_pct   REAL,                -- 日涨跌幅（%）
    UNIQUE(fund_code, nav_date)      -- 同一基金同一天不重复
);
```

> **讲解：为什么要 UNIQUE(fund_code, nav_date)？**
> 这是为了防止重复拉取数据。如果爬虫在某一天跑了两遍，第二次插入同一天的数据时会自动跳过（或 update），不会产生重复行。

**fund_holdings 表 — 持仓明细**

```sql
CREATE TABLE fund_holdings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_code   TEXT NOT NULL,       -- 基金代码
    stock_code  TEXT NOT NULL,       -- 持仓股票代码
    stock_name  TEXT,                -- 股票名称
    ratio       REAL,                -- 占净值比例（%）
    report_date TEXT,                -- 报告期，如 "2026Q1"
    UNIQUE(fund_code, stock_code, report_date)
);
```

> **讲解：report_date 为什么重要？**
> 基金持仓数据按季度披露。同一只基金每个季度可能持有不同的股票。带上 report_date 才能知道"这个持仓数据是哪个季度的"。

#### 1.3 Text2SQL：让 LLM 自己写 SQL

这是数据引擎最核心的设计思路——**不写死的 CRUD 函数，而是暴露给 LLM 三个通用方法，让 LLM 自己决定怎么查数据**。

> **讲解：传统做法 vs Text2SQL 做法**
> 传统做法：为每种查询写一个函数——`get_fund_by_code()`、`get_nav_by_date_range()`、`get_holdings_latest()`、`get_funds_by_type()`……需求一变就得加新函数。
> Text2SQL 做法：LLM 先看一眼数据库 schema（有哪些表、哪些列），然后自己生成 SQL，通过通用查询方法执行。未来加了新表或新列，无需改任何 Python 代码——LLM 看一眼新 schema 就能查。

**暴露给 LLM 的三个 Tool：**

```
┌─────────────────────────────────────────────────┐
│  Tool 1: get_db_schema()                        │
│  返回所有表名、列名、类型、示例数据（前3行）        │
│  LLM 据此知道该 JOIN 什么表、用哪个列名            │
│  无需参数                                         │
├─────────────────────────────────────────────────┤
│  Tool 2: execute_query(sql: str)                │
│  仅允许 SELECT 语句                               │
│  返回查询结果（dict 列表），自动限制 100 行         │
│  如果 SQL 错误，返回错误信息让 LLM 修正重试          │
├─────────────────────────────────────────────────┤
│  Tool 3: execute_modify(sql: str)               │
│  允许 INSERT / UPDATE / DELETE                   │
│  禁止 DROP、ALTER、不带 WHERE 的 DELETE/UPDATE     │
│  返回影响行数                                      │
└─────────────────────────────────────────────────┘
```

**LLM 使用这三个 Tool 的典型对话流程：**

```
用户："华夏成长混合最近三个月涨了多少？"
    │
    ▼
LLM 调 get_db_schema() → 看到 funds 表有 code/name，
                          fund_nav 表有 fund_code/nav_date/daily_pct
    │
    ▼
LLM 生成 SQL：
  SELECT SUM(daily_pct) FROM fund_nav
  WHERE fund_code = '000001'
    AND nav_date >= date('now', '-3 months')
    │
    ▼
LLM 调 execute_query(sql) → 得到结果 [{"SUM(daily_pct)": 5.23}]
    │
    ▼
LLM 回答："华夏成长混合近三个月累计上涨 5.23%"
```

> **讲解：Self-Correction 机制**
> LLM 生成的 SQL 可能语法错误或引用了不存在的列。捕获异常后，把错误信息原样返回给 LLM，让它根据错误提示修正 SQL。这个"生成 → 执行 → 报错 → 修正"的循环通常 1-2 次就能收敛，不需要人工干预。这是 Text2SQL 在生产项目中可行的关键。

#### 1.4 安全控制

LLM 生成的 SQL 必须经过安全校验，核心规则：

| 规则 | 适用方法 | 原因 |
|---|---|---|
| 只允许 SELECT | `execute_query` | 查询接口不该修改数据 |
| 禁止 DROP / ALTER / CREATE / TRUNCATE | `execute_modify` | 防止 LLM 幻觉删表 |
| DELETE / UPDATE 必须含 WHERE | `execute_modify` | 防止误删全表数据 |
| 默认 LIMIT 100 | `execute_query` | 防止查全表撑爆内存 |
| SQL 词法检查，非正则字符串匹配 | 两者 | 防止绕过（如用 `dr/**/op` 绕过 "DROP" 关键词检测） |

> **讲解：SQL 注入在这个架构里还是问题吗？**
> 传统 SQL 注入的风险来自**用户输入**被拼接到 SQL 中。但在这个架构里，SQL 是 LLM 生成的，不是用户输入直接拼接的。用户只提供了自然语言 query，LLM 翻译成 SQL。真正的风险很小——LLM 不会出于恶意写注入代码。但你仍需截断和校验，因为 LLM 可能"幻觉"出危险语句。

#### 1.5 数据来源：akshare

[akshare](https://github.com/akfamily/akshare) 是一个开源的 Python 金融数据接口库，封装了东方财富、天天基金等网站的公开数据。免费、无 API Key 要求。

核心函数对照：
- `akshare.fund_open_fund_info_em(fund="000001")` → fund 基本信息
- `akshare.fund_open_fund_info_em(symbol="000001", indicator="单位净值走势")` → 净值历史
- `akshare.fund_portfolio_hold_detail_em(symbol="000001")` → 持仓明细

> **安装**：`pip install akshare`

> **注意**：akshare 是同步函数，在异步环境中需要用 `asyncio.to_thread()` 包装，避免阻塞事件循环。

#### 1.6 数据加载策略

基金基本信息（`funds` 表）通常只有几千行，在 lifespan 启动时全量加载到内存字典缓存。净值数据和持仓数据按需通过 `execute_query` 查询，不缓存（因为数据量大会膨胀）。

`get_db_schema` 不需要每次对话都调用——在对话开始时调一次，结果缓存在当前 session 中即可。

---

### 2. 语义引擎（ChromaDB，已有基础）

你当前已有的 `knowledge_collection` 存放研报摘要，结构是对的。后续按需扩展：

**扩展点：**

| 当前状态 | 后续补充 |
|----------|----------|
| 单一 `knowledge_collection`（研报） | 新增 `news_collection`（每日资讯），分开检索 |
| 未分块（当前 content 较短） | 当研报全文进入时启用 langchain `RecursiveCharacterTextSplitter` |
| metadata 只有 source/url/tags | 加上 `published_at` 用于按时间过滤 |

> **讲解：为什么把研报和资讯分成两个 collection？**
> ChromaDB 中一个 collection 对应一个向量空间。研报和资讯的语言风格、时效性完全不同——混在一起检索，query "最近新能源有什么新闻" 可能返回半年前的研报。分 collection 后可以在检索时按场景选择：查研报 → `knowledge_collection`，查资讯 → `news_collection`。

---

### 3. Agent 路由层

#### 3.1 Agent 完整的 Tool 列表

将前面讨论的所有能力注册为 LLM 可调用的 Tool：

| Tool 名称 | 归属引擎 | 功能 |
|---|---|---|
| `get_db_schema` | 数据引擎 | 返回所有表的列名和示例数据 |
| `execute_query` | 数据引擎 | 执行 SELECT 查询（只能读） |
| `execute_modify` | 数据引擎 | 执行 INSERT/UPDATE/DELETE（安全过滤） |
| `search_research` | 语义引擎 | 在研报 collection 中语义检索 |
| `search_news` | 语义引擎 | 在资讯 collection 中语义检索（按日期过滤） |
| `analyze_portfolio` | 纯函数 | 持仓诊断计算（集中度/重叠度/类型互补） |
| `get_time` | 工具 | 获取当前时间（已有） |

> **讲解：为什么既有 `execute_query` 又有 `analyze_portfolio`？**
> `execute_query` 是灵活的通用查询——LLM 想查什么就生成什么 SQL。但像行业集中度这种涉及多表 JOIN + 聚合 + 外部行业映射的计算，LLM 写的 SQL 容易出错且难以调试。`analyze_portfolio` 把这个计算逻辑固化在 Python 代码中，保证正确性。两者互补：**Text2SQL 负责灵活探索，纯函数负责确定性计算。**

#### 3.2 路由器的工作流程

```
用户 query 进入
    │
    ▼
┌─────────────────────┐
│  LLM 根据 system     │  ← LLM 自己决定先调哪个 tool
│  prompt + tool 列表  │    不需要预分类
│  自主决策调用链       │
└──────┬──────────────┘
       │
       ├── "这只基金怎么样" → execute_query 查基础数据
       │                    → search_research 找相关研报
       │                    → LLM 合成回答
       │
       ├── "帮我诊断持仓" → analyze_portfolio 做精确计算
       │                  → search_research 补充风险研报
       │                  → LLM 生成诊断报告
       │
       └── "今天有什么新闻" → search_news 查最新资讯
                           → LLM 摘要
```

> **讲解：为什么不用预分类了？**
> 之前的方案是"先分类，再根据类型走不同路径"。现在有了 Text2SQL，LLM 通过 `get_db_schema` 了解数据结构后，自己就能规划调用链。分类变成了 LLM 的隐式推理，不需要额外的分类 prompt 和路由代码。这让 Agent 更灵活——用户同时问"诊断持仓 + 跟我说说这只基金"，LLM 可以并行调多个 tool。

#### 3.3 System Prompt 设计要点

```python
system_prompt = f"""
你是一个基金分析助手，帮助普通投资者理解基金产品和自己的投资组合。

你可以使用以下工具：
- get_db_schema(): 查看数据库中有哪些表和列
- execute_query(sql): 执行只读 SQL 查询（仅限 SELECT）
- search_research(query): 在研究报告知识库中搜索
- search_news(query, days=7): 搜索近期资讯
- analyze_portfolio(fund_codes: list): 分析持仓组合的健康度
- get_time(): 获取当前时间

重要规则：
1. 查数据前，先调 get_db_schema 了解表结构
2. SQL 中引用的表名和列名必须和 schema 严格一致
3. 如果 SQL 执行失败，根据错误信息修正后重试
4. 所有数字和事实必须来自查询结果，不要编造
5. 用通俗易懂的语言解释专业概念，你的用户是普通投资者
6. 在回答末尾列出数据来源
"""
```

> **讲解：这个 system prompt 的设计逻辑**
> 第1条保证 LLM 不会对着不存在的表名写 SQL。第2条防止幻觉。第3条是 Self-Correction 的关键。第4条防止 LLM 在没有调用 tool 的情况下直接瞎编。第5条适配目标用户。第6条实现可解释性。

---

### 4. 持仓分析逻辑（纯函数层）

这是整个项目中最"硬核"的部分——它不依赖 AI，纯粹是数据计算。

#### 4.1 计算流程

```
输入：[基金代码列表]
    │
    ▼
1. 遍历每只基金，查 fund_holdings 表取最新持仓
    │
    ▼
2. 按行业分类每只基金的重仓股（需要股票行业映射表）
    │
    ▼
3. 计算多只基金间的行业重叠度
    │
    ▼
4. 输出结构化指标：
    ├── 行业集中度：前3大行业总占比
    ├── 重仓股重叠：哪些股票被多只基金同时持有
    ├── 规模是否过大（百亿以上巨型基金）
    └── 类型是否互补（全是股票型？有债券型对冲吗？）
    │
    ▼
5. 将结构化指标 + 从语义引擎检索的风险研报 → 喂给 LLM 生成自然语言诊断
```

> **讲解：为什么计算和生成要分开？**
> LLM 做加减乘除不可靠。行业集中度必须用 Python 精确计算，出来的结果才是可信的。LLM 只负责最后一环：把冷冰冰的数字翻译成普通用户看得懂的话。这也是"Agent 不是万能的"——LLM 擅长的事情让它做，不擅长的交给确定性代码。

#### 4.2 股票行业映射

持仓数据告诉你"这只基金持有贵州茅台"，但没说贵州茅台是消费行业。需要一个行业映射表。

简单方案：用东方财富的股票行业分类数据，同样通过 akshare 获取，存 SQLite 一张小表即可。

---

### 5. 定时调度

三个定时任务，在 lifespan 中通过 `asyncio.create_task` 启动：

| 任务 | 频率 | 做什么 |
|---|---|---|
| 资讯更新 | 每日 9:00 | 爬取最新资讯 → 入库 SQLite → 向量化到 news_collection |
| 净值更新 | 每日 15:30 | 拉取所有已关注的基金当日净值 |
| 持仓更新 | 每季度一次 | 等基金季报披露后更新 fund_holdings |

```python
# 学习版实现（不需要 APScheduler）
async def daily_news_job():
    while True:
        await asyncio.sleep(86400)  # 24小时
        await update_news()
```

> **讲解：为什么不用 APScheduler？**
> APScheduler 功能全但概念多。对于学习项目，`while True + sleep` 足够你理解轮询机制。面试时如果有人问"为什么不健壮"，你可以回答"生产环境会换成 Celery/Airflow，这里用轮询是为了减少外部依赖"。这样反而展示了你有意选择复杂性。

---

### 6. API 层

#### 6.1 端点设计

| 方法 | 路径 | 输入 | 输出 |
|---|---|---|---|
| POST | `/chat` | `{"user_id": "...", "query": "..."}` | `{"answer": "...", "sources": [...]}` |
| POST | `/portfolio` | `{"user_id": "...", "funds": ["000001", "000002"]}` | `{"diagnosis": "...", "metrics": {...}}` |
| GET | `/digest` | 无 | `{"date": "...", "summary": "...", "items": [...]}` |
| GET | `/search` | `?q=新能源&top_k=5` | `{"results": [...]}` |

#### 6.2 sources 返回结构

每次回答附带引用来源，这是让 Agent 回答**可信**的关键：

```json
{
  "answer": "华夏成长混合主要投资于...",
  "sources": [
    {"type": "research", "title": "中国叉车行业...", "author": "头豹研究院", "url": "..."},
    {"type": "fund_data", "code": "000001", "field": "持仓", "date": "2026Q1"}
  ]
}
```

> **讲解：sources 为什么重要？**
> 普通基民不信任 AI 的幻觉。附上信息来源后，用户可以自己去验证。对于简历项目，这也是展示"可解释性 AI"能力的一个点。

---

### 7. 开发顺序（由易到难）

每个阶段完成后你都能看到可运行的结果，不必等到最后。

**阶段一：SQLite 建表 + Schema 暴露**（难度 ★★☆）

- 在 SQLite 中创建三张表（funds / fund_nav / fund_holdings）
- 实现 `get_db_schema` 方法，返回所有表的列名 + 示例数据
- 验证：调用 `get_db_schema` 能看到正确的表结构输出

**阶段二：Text2SQL 核心（execute_query + execute_modify）**（难度 ★★★）

- 实现带安全过滤的 `execute_query`（仅允许 SELECT，自动 LIMIT）
- 实现带安全过滤的 `execute_modify`（禁止 DROP/ALTER/无WHERE删改）
- 实现 SQL 错误捕获 → 返回给 LLM 重试的 Self-Correction 循环
- 验证：手动构造正确和错误的 SQL 测试安全过滤是否生效

**阶段三：akshare 数据拉取 + 入库**（难度 ★★☆）

- 安装 akshare，熟悉其 API 返回格式
- 写一个脚本：输入基金代码，从 akshare 拉取数据写入 SQLite
- 验证：用 DB Browser for SQLite 可视化查看数据

**阶段四：持仓分析纯函数**（难度 ★★★）

- 实现 `analyze_portfolio(fund_codes)` 函数
- 内部调用 `execute_query` 取持仓数据（复用而非重复造轮子）
- 实现行业分类 + 集中度/重叠度计算
- 验证：用几只典型基金测试，确认计算结果正确

**阶段五：语义引擎扩展**（难度 ★★☆）

- 新增 `news_collection`（ChromaDB）
- 实现 `search_research` 和 `search_news` 两个 tool
- 支持按日期范围过滤资讯
- 验证：分别对两个 collection 检索，看结果是否相关

**阶段六：Agent Tool 注册 + 对话集成**（难度 ★★★☆）

- 将全部 7 个 tool 注册到 Agent（修改 `main.py` 的 tool 列表 + func_mach）
- 设计完整的 system prompt
- 实现 LLM 并行调用 tool 的逻辑（你已有的 `asyncio.gather` 可以复用）
- 验证：终端对话测试完整流程

**阶段七：定时任务**（难度 ★★☆）

- 用 `asyncio.create_task` 在 lifespan 中启动定时循环
- 每日资讯更新：爬取 → 入库 SQLite → 向量化到 news_collection
- 净值更新：定时拉取最新净值数据
- 验证：手动触发一次任务，检查数据是否更新

**阶段八：FastAPI 全量集成**（难度 ★★★）

- 所有子模块通过 lifespan 组装启动
- 实现 4 个 API 端点
- 添加全局异常处理和用户友好的错误提示
- 补充 sources 引用到每个回答
- 验证：用 Swagger UI 测试每个端点

**阶段九：打磨**（难度 ★★☆）

- 错误提示对普通用户友好（"暂时查不到数据，请稍后重试" 而非 traceback）
- 持仓诊断输出配上文字版资产配置分析
- 补充 README（架构图 + 启动方式 + API 示例）

---

### 8. 你可能会问的问题

**Q: akshare 的数据会不会过期/失效？**

有可能。akshare 依赖爬取东方财富等网站的公开 API，这些接口偶尔会变。解决方案：关注 akshare 的更新，或备选 `baostock`（更稳定但数据少）。

**Q: 为什么不直接用天天基金 API？**

天天基金没有公开 API，akshare 帮你做了反向工程。如果你想更可靠，可以自己基于你的爬虫框架（`资源搜索/src/crawlers/`）模仿 `eastmoney_fund.py` 扩展基金数据爬取。

**Q: 向量数据库目前只有 ChromaDB 吗？我可以换成 Milvus/Qdrant 吗？**

ChromaDB 适合本项目量级（万级文档）。如果简历上想展示多向量库经验，可以后续加一个抽象层，支持切换后端。但第一版用 ChromaDB 足够了——它和 SQLite 一样是"单文件、零配置"的定位。

**Q: 持仓诊断到底有什么价值？**

普通基民最常见的错误是：买了很多基金，以为分散了风险，结果这些基金重仓股几乎一样（比如全买了白酒）。你的 Agent 能指出这个问题，就是实打实的价值。
