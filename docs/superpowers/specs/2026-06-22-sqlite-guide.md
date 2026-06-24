# SQLite 快速上手指南

> 面向本项目的实战教程。读完你会知道怎么建表、查数据，以及如何在 Python 里操作 SQLite。

---

## 1. SQLite 是什么

SQLite 是一个**嵌入式关系型数据库**。和 MySQL 的区别：

| | SQLite | MySQL |
|---|---|---|
| 安装 | 不需要，Python 自带 `sqlite3` 模块 | 需要安装服务端 |
| 存储 | 一个 `.db` 文件 | 独立服务进程管理 |
| 适用场景 | 单机应用、移动 App、学习项目 | 多用户并发访问、Web 服务集群 |
| 启动方式 | `import sqlite3` 即可 | `systemctl start mysql` |

**本项目选 SQLite 的理由**：和 ChromaDB 一样零配置，项目拷到任何机器就能跑，不依赖外部服务。

---

## 2. 基本概念

### 表（Table）

数据库里存数据的地方。可以把它想象成一个 Excel 表格：

```
funds 表：
┌──────────┬────────────────┬───────────┬──────────┐
│  code    │  name           │ fund_type │ manager  │
├──────────┼────────────────┼───────────┼──────────┤
│  000001  │ 华夏成长混合     │ 混合型     │ 王经理    │
│  000002  │ 南方现金增利     │ 货币型     │ 李经理    │
│  000003  │ 易方达蓝筹精选   │ 股票型     │ 张经理    │
└──────────┴────────────────┴───────────┴──────────┘
```

每一行叫一条**记录（Row）**，每一列叫一个**字段（Column）**。

### 主键（Primary Key）

用来唯一标识一条记录。比如 `code`（基金代码）天然适合做主键——不会有两只基金用同一个代码。

### 外键（Foreign Key）

一张表引用另一张表的主键。比如 `fund_nav` 表中的 `fund_code` 字段引用 `funds` 表的 `code`，说明"这条净值记录属于这只基金"。

---

## 3. Python 中操作 SQLite

### 3.1 连接数据库

```python
import sqlite3

# 连接（文件不存在会自动创建）
conn = sqlite3.connect("funds.db")

# 获取游标 — 通过游标执行 SQL
cur = conn.cursor()
```

> **讲解：游标（Cursor）是什么？**
> 游标是你的"操作手柄"。你告诉游标要执行什么 SQL，游标替你去数据库里干活。一个连接可以创建多个游标，但通常一个就够用了。

### 3.2 建表

```python
cur.execute("""
    CREATE TABLE IF NOT EXISTS funds (
        code      TEXT PRIMARY KEY,
        name      TEXT NOT NULL,
        fund_type TEXT,
        scale     REAL
    )
""")
conn.commit()  # 提交事务，写入生效
```

> **讲解：`IF NOT EXISTS` 的意义**
> 如果表已经存在，没有这个子句会报错。加上后，多次执行建表脚本是安全的——第二次运行时跳过，不会破坏已有数据。

> **讲解：`conn.commit()` 为什么需要？**
> SQLite 默认开启事务。`execute()` 之后的修改只在"暂存区"，`commit()` 才真正写入磁盘。如果忘了 commit，程序关闭后数据会丢失。

**SQLite 常用数据类型：**

| SQLite 类型 | Python 对应 | 项目中的用途 |
|---|---|---|
| `TEXT` | `str` | 基金代码、名称、日期 |
| `REAL` | `float` | 净值、费率、比例 |
| `INTEGER` | `int` | 自增 ID |

SQLite 的类型系统比较宽松——你写 `TEXT` 的列存数字也不会报错。但**写好类型声明**是给读代码的人看的，表示你的意图。

### 3.3 插入数据

```python
# 插入单条
cur.execute(
    "INSERT INTO funds (code, name, fund_type, scale) VALUES (?, ?, ?, ?)",
    ("000001", "华夏成长混合", "混合型", 52.3)
)
conn.commit()
```

**为什么用 `?` 而不是直接拼字符串？**

```python
# 错误示范 — SQL注入风险！
cur.execute(f"INSERT INTO funds VALUES ('{code}', '{name}')")

# 正确做法 — 参数化查询
cur.execute("INSERT INTO funds VALUES (?, ?)", (code, name))
```

> **讲解：SQL 注入**
> 假设 `name` 的值是 `'); DROP TABLE funds; --`。拼字符串的方式会把这段恶意代码当作 SQL 执行，直接删掉整张表。参数化查询用 `?` 占位符，传给 execute 的第二个参数，SQLite 会自动做转义，不可能被执行。

**批量插入：**

```python
data = [
    ("000001", "华夏成长混合", "混合型", 52.3),
    ("000002", "南方现金增利", "货币型", 180.0),
    ("000003", "易方达蓝筹精选", "股票型", 350.5),
]
cur.executemany(
    "INSERT OR IGNORE INTO funds (code, name, fund_type, scale) VALUES (?, ?, ?, ?)",
    data
)
conn.commit()
```

> **讲解：`INSERT OR IGNORE`**
> 普通 `INSERT` 在主键重复时抛异常。`INSERT OR IGNORE` 在主键重复时静默跳过，非常适合"可能重复拉取数据"的场景——不会因重复插入而崩溃。

### 3.4 查询数据

```python
# 查全部
cur.execute("SELECT * FROM funds")
rows = cur.fetchall()  # 返回列表，每行是 tuple
# [("000001", "华夏成长混合", "混合型", 52.3), ("000002", ...)]

# 条件查询
cur.execute("SELECT name, fund_type FROM funds WHERE code = ?", ("000001",))
row = cur.fetchone()  # 只取一行
# ("华夏成长混合", "混合型")

# 模糊查询
cur.execute("SELECT * FROM funds WHERE name LIKE ?", ("%蓝筹%",))
# % 是通配符，"%蓝筹%" 匹配所有名字里包含"蓝筹"的基金
```

> **讲解：`fetchone` vs `fetchall`**
> `fetchone` 返回一条 tuple，没查到返回 `None`。`fetchall` 返回列表（可能空列表 `[]`）。大数据量时不要 `fetchall`——几万条数据一次性拉出来会撑爆内存。用 `fetchmany(n)` 分段取，或者直接遍历游标（游标本身是可迭代的）。

**查询结果转为字典：**

默认返回 tuple，靠索引访问不直观。改连接配置：

```python
conn = sqlite3.connect("funds.db")
conn.row_factory = sqlite3.Row  # 让每行返回 dict-like 对象

cur = conn.cursor()
cur.execute("SELECT * FROM funds WHERE code = ?", ("000001",))
row = cur.fetchone()
print(row["name"])   # "华夏成长混合"，不再用 row[1]
```

### 3.5 更新和删除

```python
# 更新
cur.execute(
    "UPDATE funds SET scale = ? WHERE code = ?",
    (60.5, "000001")
)
conn.commit()

# 删除
cur.execute("DELETE FROM fund_nav WHERE nav_date < ?", ("2025-01-01",))
conn.commit()
```

> **⚠️ 警告：**
> `DELETE FROM funds`（不带 WHERE）会删掉整张表的所有数据。
> `DELETE FROM funds WHERE ...` 只删满足条件的行。
> **执行 DELETE/UPDATE 前，先在脑子过一遍 WHERE 条件。**

### 3.6 关闭连接

```python
conn.close()
```

或者用 `with` 语句自动关闭：

```python
with sqlite3.connect("funds.db") as conn:
    cur = conn.cursor()
    cur.execute("SELECT * FROM funds")
    # with 块结束时自动 commit + close
```

---

## 4. 本项目的表设计回顾

```sql
-- 基金基础信息
CREATE TABLE IF NOT EXISTS funds (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    fund_type   TEXT,
    manager     TEXT,
    company     TEXT,
    scale       REAL,
    fee_rate    REAL,
    created_at  TEXT
);

-- 净值历史（每天一行）
CREATE TABLE IF NOT EXISTS fund_nav (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_code   TEXT NOT NULL,
    nav_date    TEXT NOT NULL,
    unit_nav    REAL,
    acc_nav     REAL,
    daily_pct   REAL,
    UNIQUE(fund_code, nav_date)
);

-- 持仓明细（每季度每只股票一行）
CREATE TABLE IF NOT EXISTS fund_holdings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_code   TEXT NOT NULL,
    stock_code  TEXT NOT NULL,
    stock_name  TEXT,
    ratio       REAL,
    report_date TEXT,
    UNIQUE(fund_code, stock_code, report_date)
);
```

**设计要点回顾：**

- `AUTOINCREMENT`：让 SQLite 自动生成递增的整数 ID，你不需要手动填
- `UNIQUE` 约束：防止重复插入，结合 `INSERT OR IGNORE` 使用
- `TEXT` 存日期：SQLite 没有日期类型，用 ISO 格式的字符串（`"2026-06-22"`）即可，排序和比较都正确

> **讲解：为什么日期用 TEXT 而不是单独存年/月/日？**
> SQLite 没有 DATE 类型（MySQL 有）。用 `"2026-06-22"` 这种 ISO 格式的 TEXT，可以直接用 `WHERE nav_date > "2026-01-01"` 做范围查询，字符串比较的结果和日期比较一致。如果拆成 year/month/day 三列，范围查询会变得很麻烦。

---

## 5. 实用技巧

### 5.1 用上下文管理器封装

避免每次都手动 commit/close：

```python
from contextlib import contextmanager

@contextmanager
def get_db(db_path: str = "funds.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# 使用
with get_db() as conn:
    cur = conn.cursor()
    cur.execute("SELECT * FROM funds")
    rows = cur.fetchall()
```

### 5.2 开启 WAL 模式提升并发

```python
conn.execute("PRAGMA journal_mode=WAL")
```

WAL（Write-Ahead Logging）模式下，读写可以同时进行，不会互相阻塞。对于有定时写入 + 随时查询的场景很重要。

### 5.3 用 DB Browser 可视化

下载 [DB Browser for SQLite](https://sqlitebrowser.org/)，打开你的 `.db` 文件，可以看到表结构、数据、执行 SQL。调试时比命令行直观很多。

---

## 6. 一个完整示例

把本节所有知识串起来：

```python
import sqlite3

# 1. 连接
conn = sqlite3.connect("funds.db")
conn.row_factory = sqlite3.Row

# 2. 建表
conn.execute("""
    CREATE TABLE IF NOT EXISTS funds (
        code      TEXT PRIMARY KEY,
        name      TEXT NOT NULL,
        fund_type TEXT,
        scale     REAL
    )
""")

# 3. 插入
funds_data = [
    ("000001", "华夏成长混合", "混合型", 52.3),
    ("000002", "南方现金增利", "货币型", 180.0),
    ("000003", "易方达蓝筹精选", "股票型", 350.5),
    ("000004", "天弘沪深300联接", "指数型", 420.0),
]
conn.executemany(
    "INSERT OR IGNORE INTO funds (code, name, fund_type, scale) VALUES (?, ?, ?, ?)",
    funds_data
)
conn.commit()

# 4. 查询 — 规模大于100亿的基金
rows = conn.execute(
    "SELECT code, name, scale FROM funds WHERE scale > ? ORDER BY scale DESC",
    (100,)
).fetchall()

for row in rows:
    print(f"{row['code']} {row['name']} 规模: {row['scale']}亿")

# 5. 关闭
conn.close()
```

输出：
```
000004 天弘沪深300联接 规模: 420.0亿
000003 易方达蓝筹精选 规模: 350.5亿
000002 南方现金增利 规模: 180.0亿
```

---

## 7. 常见错误速查

| 错误信息 | 原因 | 解决 |
|---|---|---|
| `no such table: xxx` | 表还没创建 | 先执行 `CREATE TABLE` |
| `UNIQUE constraint failed` | 主键或 UNIQUE 列重复插入 | 用 `INSERT OR IGNORE` 或先查重 |
| `database is locked` | 并发写入冲突 | 开启 WAL 模式 |
| `OperationalError: no such column` | SQL 里列名写错了 | 检查拼写，用 `PRAGMA table_info(表名)` 看列名 |

祝顺利。数据库这层通了之后，后续的持仓分析就是在这上面做 Python 计算，会轻松很多。
