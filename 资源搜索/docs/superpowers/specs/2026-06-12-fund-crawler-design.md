# 基金投资研报爬虫 — 设计文档

## 目标

为基金分析 Agent 搜集中文公募基金领域的研究报告、市场分析、基金经理观点等文本语料，输出为 JSONL 格式，供下游 RAG 知识库使用。

## 运行模式

首次全量爬取 + 架构预留增量更新能力。增量阶段通过日期过滤和 URL 去重实现。

## 数据源

| 来源 | 内容类型 | 获取方式 | 优先级 |
|---|---|---|---|
| 东方财富研报中心 (data.eastmoney.com) | 券商研报、行业分析、基金研究 | HTTP JSONP API | P0 |
| 天天基金资讯 (fund.eastmoney.com) | 基金新闻、经理观点、基金分析 | HTTP API | P0 |
| 晨星中国 (cn.morningstar.com) | 基金评级文章、投资教育 | HTTP + Playwright fallback | P1 |
| 中国证券投资基金业协会 (amac.org.cn) | 行业统计、政策研究、公募数据 | HTTP | P1 |

## 技术栈

- Python 3.11+
- `httpx` — 异步 HTTP 客户端，API 数据获取
- `BeautifulSoup4` / `lxml` — HTML 解析
- `Playwright` — JS 渲染页面 fallback（仅晨星等少量站点）
- `asyncio` — 并发调度

## 目录结构

```
资源搜索/
  src/
    __init__.py
    crawlers/
      __init__.py
      base.py            # 基类：限速、重试、UA 轮换、去重
      eastmoney_research.py  # 东方财富研报
      eastmoney_fund.py      # 天天基金资讯
      morningstar.py         # 晨星中国
      amac.py                # 基金业协会
    storage.py           # JSONL 读写、增量去重、断点续爬
    pipeline.py          # 并发调度编排
  data/                  # 爬取结果输出
  requirements.txt
  run.py                 # CLI 入口
```

## 输出格式

JSONL，每行一条记录：

```json
{
  "id": "md5(source+url)",
  "source": "eastmoney_research",
  "url": "https://...",
  "title": "xxx",
  "author": "xx证券",
  "published_at": "2026-06-12",
  "crawled_at": "2026-06-12T16:00:00",
  "content": "正文全文（Markdown）",
  "tags": ["基金", "行业分析"],
  "category": "研报"
}
```

## 核心模块设计

### base.py — 爬虫基类

- 速率控制：每个域名维护独立令牌桶，默认 2 req/s
- 重试策略：指数退避，最多 3 次，仅重试 5xx 和网络错误
- User-Agent 池：随机轮换，降低反爬概率
- 去重：内存 Bloom filter + 文件持久化 URL 集合
- 增量标记：记录每个源上次爬取时间戳

### storage.py — 存储层

- 追加写 JSONL，每条记录一行
- `seen_urls` 集合持久化到本地文件，支持断点续爬
- 按来源分文件或统一单文件，由配置决定（默认按来源分文件）
- 写入时自动去重（检查已有 id）

### pipeline.py — 调度器

- 顺序执行各爬虫，单个爬虫内部 asyncio 并发
- 提供 `--source` 参数指定只跑某个源
- 提供 `--incremental` 参数启用增量模式
- 进度输出：已爬 N 条 / 新增 M 条

### CLI 入口 (run.py)

```
python run.py                    # 全量爬取所有源
python run.py --source eastmoney # 只爬东方财富
python run.py --incremental      # 增量更新
```

## 反爬与合规

- 所有请求携带合法 User-Agent
- 遵守各站点 robots.txt（启动时检查）
- 限速默认 2 req/s，可通过配置调整
- 仅爬取公开可访问页面，不绕过登录/付费墙
- 数据仅供个人研究使用

## 不在范围内

- 不爬取付费/登录墙后的内容
- 不做 PDF 解析（研报 PDF 下载链接记录但不处理，由下游 mineru 等其他工具处理）
- 不做实时推送/通知
- 不做网页前端展示
