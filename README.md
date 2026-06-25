# 基金分析 Agent

面向普通基民的智能基金分析助手 — 用自然语言查询基金、分析持仓、获取市场动态。

LLM + Tool Calling + 向量数据库 + 结构化数据的 Agent 学习项目。

## 技术栈

| 层级 | 技术 |
|------|------|
| 框架 | FastAPI（异步 SSE 流式响应） |
| LLM | DeepSeek（deepseek-v4-flash），OpenAI 兼容接口 |
| Web 搜索 | Tavily |
| 向量数据库 | ChromaDB（知识库 / 对话记忆 / 工具数据临时存储） |
| 关系数据库 | SQLite（基金持仓 / 净值 / 对话历史） |
| 数据源 | akshare（天天基金 / 东方财富公开数据） |
| 前端 | 原生 HTML + CSS + JS（无框架） |
| Embedding | sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2) |

## 架构

```
FastAPI 入口 (app.py) → 静态前端 /
  ├── Agent 核心 (agent.py)
  │   ├── LLM 推理（DeepSeek，Function Calling + 流式输出）
  │   ├── 16 个 Tool（搜索 / 新闻 / 知识检索 / 基金 CRUD / akshare 数据 / 行业分析 / 热度排行）
  │   ├── 大数据自动切片（存入 ChromaDB，LLM 按需检索）
  │   └── 对话历史（SQLite 持久化 + ChromaDB 向量记忆）
  ├── 路由层 (routers/)
  │   ├── /chat/query  — 对话（SSE 流式）
  │   ├── /chat/sessions|messages|session — 对话历史管理
  │   ├── /fund/query_fund|get_fund_rank|get_fund_nav|get_fund_hold — 基金数据查询
  │   └── /fund/holdings|submit_fund|remove_fund — 持仓管理
  ├── 数据层 (sqlite_db/)
  │   ├── 基金持仓 CRUD + 对话历史持久化
  │   └── Text2SQL（LLM 自主 SQL 生成 + 安全过滤）
  └── 数据采集 (akshare_func/, 资源搜索/)
```

## 快速开始

### 环境要求

- Python 3.10+
- Windows / Linux / macOS

### 安装

```bash
git clone https://github.com/l1141275900/fund_agent.git
cd fund_agent

python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate

pip install fastapi uvicorn openai chromadb sentence-transformers tavily-python akshare httpx pydantic
```

### 配置 API Key

```bash
# Windows PowerShell
$env:DEEPSEEK_API_KEY = "your-key"
$env:TAVILY_API_KEY = "your-key"

# Linux/Mac
export DEEPSEEK_API_KEY="your-key"
export TAVILY_API_KEY="your-key"
```

### 启动

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

- 前端界面：`http://localhost:8000`
- Swagger 文档：`http://localhost:8000/docs`

## API

### 对话

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat/query` | 对话接口（SSE 流式，含思考过程 + 工具调用状态） |
| GET | `/chat/sessions` | 获取所有对话记录 |
| GET | `/chat/messages?session_id=` | 获取指定对话消息 |
| DELETE | `/chat/session?session_id=` | 删除对话 |

### 基金数据 & 持仓

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/fund/query_fund?fund_code=` | 查询基金详情 |
| GET | `/fund/get_fund_rank?fund_type=` | 基金排行（全部/股票型/混合型/债券型/指数型/QDII/FOF） |
| GET | `/fund/get_fund_nav?fund_code=` | 基金净值历史 |
| GET | `/fund/get_fund_hold?fund_code=&date=` | 基金持仓股票 |
| PUT | `/fund/submit_fund` | 批量添加持仓 |
| GET | `/fund/holdings` | 查看全部持仓 |
| DELETE | `/fund/remove_fund?fund_code=` | 删除持仓 |

## Agent Tool 列表

| Tool | 说明 |
|------|------|
| `search` | Tavily 互联网搜索 |
| `get_time` | 获取当前时间 |
| `knowledge_retriever` | ChromaDB 研报知识库语义检索 |
| `get_news` | 20+ 平台热点新闻 |
| `agent_add_preference` | 记录用户偏好 |
| `get_all_funds` | 查询用户持仓 |
| `get_funds_by_code` | 按代码查持仓基金 |
| `insert_one_fund_by_code` | 按代码添加持仓 |
| `get_akshare_fund_nav` | 基金净值历史 |
| `get_akshare_rank_by_type` | 按类型基金排行 |
| `get_akshare_data_by_code` | 基金基础信息 |
| `get_fund_holdings` | 基金持仓股票 |
| `get_akshare_stock_fund_flow` | 行业资金流向 |
| `get_akshare_hot_rank` | 市场热度排行 |
| `get_akshare_sw_index_third_info` | 申万三级行业估值 |
| `retrieve_tool_data` | 检索已切片的大数据 |

## 项目状态

🚧 **开发中**

- [x] Agent 核心框架（16 个 Tool + 流式输出 + 大数据自动切片）
- [x] 前端 UI（对话 / 持仓管理 / 每日关注）
- [x] SQLite 对话历史持久化
- [x] ChromaDB 三层记忆（知识库 + 对话 + 工具数据临时存储）
- [x] akshare 多维度数据（基金详情 / 净值 / 排行 / 持仓 / 行业流向 / 热度）
- [x] 持仓管理（添加 / 查询 / 删除）
- [ ] 持仓诊断分析（组合健康度计算）
- [ ] 定时任务（每日资讯 / 净值更新）
- [ ] 每日关注自动推送

## 目录结构

```
agent_learn1/
├── app.py                  # FastAPI 入口 + lifespan
├── agent.py                # Agent 核心（LLM + 16 个 Tool）
├── memory.py               # ChromaDB 用户记忆系统
├── tool_memory.py          # 大体积工具数据临时存储
├── env.py                  # 环境配置
├── static/                 # 前端 UI
├── routers/                # API 路由
├── schema/                 # Pydantic 数据模型
├── knowledge/              # 研报知识库（ChromaDB）
├── sqlite_db/              # SQLite 数据层（持仓 + 对话历史）
├── akshare_func/           # akshare 数据采集封装
├── tests/                  # 测试
└── 资源搜索/               # 数据爬虫子项目
```

## License

MIT
