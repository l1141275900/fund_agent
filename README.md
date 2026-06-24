# 基金分析 Agent

面向普通基民的智能基金分析助手。用户无需懂财经术语，用自然语言即可查询基金信息、获取每日资讯、诊断持仓。

同时这也是一个 Agent 开发学习项目，探索 LLM + Tool Calling + 向量数据库 + Text2SQL 的架构实践。

## 技术栈

- **框架**: FastAPI（异步 SSE 流式响应）
- **LLM**: DeepSeek（deepseek-v4-flash），通过 OpenAI 兼容接口调用
- **搜索引擎**: Tavily
- **向量数据库**: ChromaDB（语义检索知识库 + 对话记忆）
- **关系型数据库**: SQLite（基金基础信息、净值、持仓）
- **数据源**: akshare（中国基金公开数据）
- **Embedding**: sentence-transformers（paraphrase-multilingual-MiniLM-L12-v2）

## 架构

```
FastAPI 入口 (app.py)
  ├── Agent 核心 (agent.py)
  │   ├── LLM 推理（DeepSeek，支持 Function Calling + 流式输出）
  │   ├── Tool 系统（搜索 / 新闻 / 知识检索 / 时间 / 偏好记忆）
  │   ├── 语义引擎（ChromaDB 研报知识库）
  │   └── 记忆系统（ChromaDB 对话历史 + 用户偏好）
  ├── 数据层 (sqlite_db/)
  │   ├── 基金基础信息 CRUD
  │   ├── 净值 / 持仓数据管理
  │   └── Text2SQL（LLM 自主生成 SQL 查询）
  ├── 路由层 (routers/)
  │   ├── POST /chat/query — 对话接口
  │   └── POST /chat/funds — 基金数据查询
  └── 数据采集 (akshare_func/, 资源搜索/)
```

## 快速开始

### 环境要求

- Python 3.10+
- Windows / Linux / macOS

### 安装

```bash
# 克隆项目
git clone <repo-url>
cd agent_learn1

# 创建虚拟环境
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 安装依赖
pip install fastapi uvicorn openai chromadb sentence-transformers tavily-python akshare httpx pydantic
```

### 配置 API Key

```bash
# Windows PowerShell
$env:DEEPSEEK_API_KEY = "your-deepseek-api-key"
$env:TAVILY_API_KEY = "your-tavily-api-key"

# Linux/Mac
export DEEPSEEK_API_KEY="your-deepseek-api-key"
export TAVILY_API_KEY="your-tavily-api-key"
```

### 启动

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

访问 `http://localhost:8000/docs` 查看 Swagger API 文档。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat/query` | 对话接口，支持流式 SSE 响应 |
| POST | `/chat/funds` | 根据基金代码查询基金数据 |

### 示例

```bash
curl -X POST http://localhost:8000/chat/query \
  -H "Content-Type: application/json" \
  -d '{"session_id": "user1", "query": "推荐几只新能源方向的基金"}'
```

## 项目状态

🚧 **开发中** — 当前已完成：

- [x] Agent 核心框架（LLM + Tool Calling + 流式输出）
- [x] 语义检索引擎（ChromaDB 研报知识库）
- [x] 用户偏好记忆与对话历史
- [x] 多平台新闻搜索（20+ 平台）
- [x] SQLite 数据层（基金信息 / 净值 / 持仓 CRUD）
- [x] Text2SQL（LLM 自主 SQL 生成 + 安全过滤）
- [x] akshare 基金数据采集
- [x] 基础测试

待完成：

- [ ] 持仓诊断分析（组合健康度计算）
- [ ] 定时任务（每日资讯 / 净值更新）
- [ ] 语义引擎扩展（新闻专用 collection）
- [ ] API 完善（/portfolio、/digest 端点）
- [ ] 回答来源引用（sources）

详见 `docs/superpowers/specs/` 下的设计文档。

## 目录结构

```
agent_learn1/
├── app.py                  # FastAPI 入口
├── agent.py                # Agent 核心（LLM + Tool 系统）
├── memory.py               # ChromaDB 记忆系统
├── env.py                  # 环境配置
├── routers/                # API 路由
├── schema/                 # Pydantic 数据模型
├── knowledge/              # 知识库（ChromaDB）
├── sqlite_db/              # SQLite 数据层 + Text2SQL
├── akshare_func/           # akshare 数据采集封装
├── tests/                  # 测试
├── docs/                   # 设计文档
└── 资源搜索/               # 数据采集子项目（爬虫）
```

## License

MIT
