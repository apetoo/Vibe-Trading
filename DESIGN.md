# 产业链知识库（Industry Chain Knowledge Graph）— 设计文档

> 本文件覆盖此前的「持仓显示功能」设计草稿（该功能已并入 main，见 commit baa658a/9220da9）。
> 本设计针对全新需求：**结构化的产业链知识图谱 + 可视化编辑 + AI 对话更新 + 复用给 AI 分析**。
> 试点赛道：AI 算力产业链（CPO / OCS / 光芯片 / PCB 四方向 + 8-12 只龙头股）。

## 0. 需求成立性结论（office-hours 阶段一澄清产出）

经 8 轮苏格拉底式澄清，需求**成立且不重复**。关键判断：

- 现有 `sector-rotation` skill 做的是**行业间景气度轮动**（煤炭→钢铁→家电的宏观传导），字段是景气度/动量/估值分位。
- 本需求做的是**单赛道内技术链路垂直结构**（CPO→光芯片→光模块的微观链），字段是国产化率/毛利率中枢/上下游依赖/技术替代进度。
- 两者字段语义完全不同，**不复用 sector-rotation 字段**，为产业链场景全新设计表结构（符合用户"不照搬其他领域表结构"硬约束）。

### 0.1 已确认的 8 项决策

| # | 决策点 | 选择 |
|---|--------|------|
| D1 | 知识粒度 | 结构化字段 + 人工/AI 撰写的可读解读段落（200-500 字/节点） |
| D2 | 历史回溯颗粒度 | 节点级版本快照（每次编辑写一条 versions 记录） |
| D3 | 溯源强度 | 单源强制溯源（sources 表）+ 交叉验证状态字段（unverified/cross_verified/disputed） |
| D4 | AI 写入路径 | AI 起草 → 写入 pending_changes 待审区 → 人工在页面采纳才生效 |
| D5 | AI 主动调用引导 | 三重：查询工具 + industry-chain skill（description 注入系统提示）+ 自动注入钩子 |
| D6 | 注入范围 | 个股产业链切片（所属节点 + 父链路 + 同层竞争对手 + 关键数字，约 800-1500 token） |
| D7 | 试点范围 | 4 技术方向 + 8-12 只龙头股 |
| D8 | 页面形态 | 树导航 + 节点编辑面板（同 Portfolio.tsx 范式，不做图形化连线） |

## 1. 目标

在 Vibe-Trading 中新增一个**产业链知识图谱**模块，解决"分析个股缺产业链垂直上下文"的痛点。三个产出形态：

1. **可视化页面** `/industry-chain`：树状浏览整个图谱 + 节点编辑面板 + 待审区。
2. **AI 对话更新**：AI 理解自然语言更新意图 → 起草 pending change → 人工采纳。
3. **复用给 AI**：分析个股时自动/主动注入该股产业链切片，让 AI 天然带产业链视角。

## 2. 真实架构对接点（CodeGraph + 源码核查）

### 2.1 后端集成范式（镜像 portfolio_routes / goal store）

| 关注点 | 仓库现状 | 本模块落点 |
|--------|----------|------------|
| HTTP 路由 | `agent/src/api/portfolio_routes.py` 导出 `register_portfolio_routes(app, require_auth)`，在 `api_server.py` 注册 | 新建 `agent/src/api/industry_chain_routes.py`，导出 `register_industry_chain_routes(app, require_auth=None)`，`api_server.py` +2 行注册 |
| 鉴权 | `require_auth` (api_server.py:651)，`register_*_routes` 用 `require_auth=None` + sys.modules 回退（镜像 alpha_routes.py:346） | 同模式 |
| SQLite 范式基准 | `agent/src/goal/store.py`：`~/.vibe-trading/sessions.db` + `sqlite3` stdlib + `_synchronized` 线程锁 + `_DB_PATH_ENV` 环境覆盖 + ISO 时间戳 + JSON 列 | 新建 `agent/src/industry_chain/store.py`，DB 路径 `~/.vibe-trading/industry_chain.db`，env `VIBE_TRADING_INDUSTRY_CHAIN_DB_PATH`，完全镜像 goal/store.py 的连接/锁/schema 迁移模式 |
| 异步阻塞 | portfolio_routes 用 `asyncio.to_thread` 包同步调用 | 本模块 store 是本地 SQLite（快），但写操作仍走 `asyncio.to_thread` 保持一致 |
| 异常处理 | 具名捕获 + `_redact_text` 脱敏 | 同模式（本模块数据非敏感金融持仓，但仍走具名捕获） |

### 2.2 Agent 工具体系（镜像 manage_portfolio_tool）

- 工具继承 `BaseTool`（agent/src/agent/tools.py:13），有 `name`/`description`/`parameters`/`execute`，经 `build_registry()`（agent/src/tools/__init__.py:66）自动发现注册。
- 新建两个工具：
  - `agent/src/tools/industry_chain_query_tool.py` → `IndustryChainQueryTool`（name=`get_industry_chain_context`，**只读**，供 AI 分析个股时查询产业链切片）
  - `agent/src/tools/industry_chain_draft_tool.py` → `IndustryChainDraftTool`（name=`draft_industry_chain_update`，起草 pending change，**非只读**）

### 2.3 Skill 体系（引导 AI 主动调用 — 第二重）

- `agent/src/agent/skills.py`：`SkillsLoader` 从 `agent/src/skills/*/SKILL.md` 加载，`get_descriptions()` 把每个 skill 的 **one-line description 注入系统提示**（context.py:146 `build_system_prompt`）。
- 新建 `agent/src/skills/industry-chain/SKILL.md`，其 frontmatter `description` 明写："分析个股或行业前，先用 `get_industry_chain_context` 查这只股票在产业链里的定位、国产化率、上下游、竞争对手。图谱里没有就先建。"
- 这条 description 常驻系统提示，比裸工具描述更显眼 —— 这是引导 AI 主动调用的核心钩子。

### 2.4 自动注入钩子（引导 AI 主动调用 — 第三重）

- `agent/src/agent/context.py:152` `build_messages` 已有"自动召回相关记忆注入用户消息"的成熟模式：`persistent_memory.find_relevant(user_message)` → 包成 `<recalled-memories>` 块前置到用户消息。
- **镜像这个模式**：在 `build_messages` 增加一段，用正则检测用户消息里的 A 股代码（`\b\d{6}\b` 或 `.SH/.SZ`）、港股代码、美股 ticker，若该股在图谱中，前置一个 `<industry-chain-context>` 块（个股产业链切片，D6 范围）。
- 这是**对 context.py 的最小侵入式增强**（一段检测 + 一次 store 查询 + 一个文本块），失败静默降级（图谱里没有该股就什么都不注入，不影响现有行为）。

### 2.5 前端集成范式（镜像 Portfolio.tsx）

| 关注点 | 仓库现状 | 本模块落点 |
|--------|----------|------------|
| 路由 | `frontend/src/router.tsx` lazy import + `createBrowserRouter` | +`IndustryChain` 页面 + `/industry-chain` 路由 |
| 侧边栏 | `Layout.tsx:18` `NAV` 数组 `{to, icon, label}` | +1 项 `{ to: "/industry-chain", icon: Network, label: t('layout.industryChain') }` |
| API 客户端 | `frontend/src/lib/api.ts` `request<T>(path, opts)` + `authHeaders()` | +`getIndustryChainTree`/`getNode`/`updateNode`/`getPendingChanges`/`acceptPendingChange`/`rejectPendingChange` 等方法 |
| 页面范式 | `frontend/src/pages/Portfolio.tsx`（表格 CRUD） | 新建 `frontend/src/pages/IndustryChain.tsx`（左树 + 右编辑面板） |
| i18n | `frontend/src/i18n/index.ts` | +`industryChain.*` 键（中英） |
| 测试 | Vitest + `@testing-library/react`，`__tests__` 约定 | 新建 `IndustryChain.test.tsx` |

## 3. 数据模型（SQLite schema — 为产业链场景全新设计）

DB 路径：`~/.vibe-trading/industry_chain.db`（用户可用任意 SQLite 工具直接打开，满足"不是黑盒"硬约束）。

### 3.1 表结构

```sql
-- 节点：赛道/技术方向/细分环节/个股 共用一张表，用 node_type 区分
CREATE TABLE nodes (
    node_id        TEXT PRIMARY KEY,          -- 如 "nd_a3f9c2"
    parent_id      TEXT,                      -- 父节点（赛道为 NULL），自引用
    node_type      TEXT NOT NULL,             -- track | segment | link | stock
    name           TEXT NOT NULL,             -- 显示名，如 "CPO 共封装光学"
    code           TEXT,                      -- 个股代码（仅 stock 类型），如 "300308.SZ"
    sort_order     INTEGER DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES nodes(node_id)
);
CREATE INDEX idx_nodes_parent ON nodes(parent_id);
CREATE INDEX idx_nodes_code ON nodes(code);

-- 节点版本快照（D2：节点级历史回溯）
CREATE TABLE node_versions (
    version_id     TEXT PRIMARY KEY,
    node_id        TEXT NOT NULL,
    summary        TEXT,                      -- 概要说明（这个环节是干什么的）
    narrative      TEXT,                      -- 可读解读段落（D1，200-500 字）
    market_size    TEXT,                      -- 市场规模（文本，含单位/年份，便于溯源）
    growth_rate    TEXT,                      -- 增速
    chain_position TEXT,                      -- 产业链核心地位和占比
    localization   TEXT,                      -- 国产化率、替代进度
    gross_margin   TEXT,                      -- 毛利率中枢
    tech_trend     TEXT,                      -- 技术趋势
    macro_drivers  TEXT,                      -- 宏观驱动因素（JSON 数组）
    -- 个股专属字段（stock 类型才填，其他类型 NULL）
    financials     TEXT,                      -- 核心财务数据摘要（JSON）
    operating_metrics TEXT,                   -- 良率/产能利用率等（JSON）
    customer_structure TEXT,                  -- 客户结构（JSON）
    extra          TEXT,                      -- 扩展字段（JSON），未来加字段不破坏 schema
    validation_status TEXT DEFAULT 'unverified', -- unverified | cross_verified | disputed
    snapshot_at    TEXT NOT NULL,             -- 快照时间
    snapshot_by    TEXT NOT NULL,             -- 'human' | 'agent'
    FOREIGN KEY (node_id) REFERENCES nodes(node_id)
);
CREATE INDEX idx_versions_node ON node_versions(node_id, snapshot_at);

-- 当前指针：每个节点指向其"当前生效"的版本（查询当前值 O(1)）
CREATE TABLE node_current (
    node_id        TEXT PRIMARY KEY,
    version_id     TEXT NOT NULL,
    FOREIGN KEY (version_id) REFERENCES node_versions(version_id)
);

-- 来源（D3：单源强制溯源）
CREATE TABLE sources (
    source_id      TEXT PRIMARY KEY,
    version_id     TEXT NOT NULL,             -- 关联到具体版本
    source_type    TEXT NOT NULL,             -- annual_report | prospectus | exchange_announcement | broker_report
    title          TEXT,
    publisher      TEXT,                      -- 机构/公司
    url            TEXT,
    published_date TEXT,
    cited_text     TEXT,                      -- 引用原文
    created_at     TEXT NOT NULL,
    FOREIGN KEY (version_id) REFERENCES node_versions(version_id)
);
CREATE INDEX idx_sources_version ON sources(version_id);

-- 待审变更（D4：AI 起草，人工采纳）
CREATE TABLE pending_changes (
    change_id      TEXT PRIMARY KEY,
    node_id        TEXT NOT NULL,             -- 要更新的节点（可为新节点，则 node_id 由 AI 拟）
    is_new_node    INTEGER DEFAULT 0,
    proposed_fields TEXT NOT NULL,            -- JSON：{字段名: 新值}
    proposed_sources TEXT,                    -- JSON：来源数组
    rationale      TEXT,                      -- AI 给的理由
    drafted_by     TEXT NOT NULL,             -- 'agent'
    status         TEXT DEFAULT 'draft',      -- draft | accepted | rejected
    created_at     TEXT NOT NULL,
    resolved_at    TEXT,
    resolved_by    TEXT,
    FOREIGN KEY (node_id) REFERENCES nodes(node_id)
);
CREATE INDEX idx_pending_status ON pending_changes(status);
```

### 3.2 设计要点

- **单表多类型节点**（`node_type` 区分赛道/方向/环节/个股）+ 自引用 `parent_id` 表达树。比"每种类型一张表"更灵活，符合产业链"层级可深可浅"的现实。
- **版本快照表 + 当前指针表**：每次编辑（人工或采纳 AI 草稿）都写一条新 `node_versions`，更新 `node_current` 指针。历史完整可回溯，当前值查询 O(1)。
- **数值字段用 TEXT**：市场规模"500 亿元（2024）"、国产化率"约 45%（2025E，光芯片环节）"这类带上下文的值，用 TEXT 保留溯源信息，比 float 更诚实。需要排序/筛选时解析。
- **`extra` JSON 列**：未来加字段不用 ALTER TABLE，符合 SQLite "易手动维护"诉求。
- **来源绑到 version**：每个版本快照带其来源，回溯任意历史版本都能看到当时凭据。
- **`validation_status`**：交叉验证状态徽章，注入给 AI 时优先 cross_verified，disputed 附冲突说明（D3 工程化落地）。

## 4. API 设计

```
GET    /industry-chain/tree                    -> 整棵树（节点 + 当前版本摘要）
GET    /industry-chain/nodes/{node_id}         -> 节点详情（当前版本 + 全字段 + 来源 + 版本历史）
POST   /industry-chain/nodes                   -> 新建节点（人工编辑）
PUT    /industry-chain/nodes/{node_id}         -> 更新节点（写新版本快照 + 更新指针）
DELETE /industry-chain/nodes/{node_id}         -> 删除节点（级联软删，保留历史）
GET    /industry-chain/pending                 -> 待审变更列表
POST   /industry-chain/pending/{change_id}/accept   -> 采纳（写新版本 + 标记 accepted）
POST   /industry-chain/pending/{change_id}/reject   -> 驳回
GET    /industry-chain/context?code=300308.SZ  -> 个股产业链切片（D6，供 AI 注入）
全部依赖 require_auth
```

`GET /industry-chain/context?code=` 是 AI 注入的核心端点，返回该股所属节点 + 父链路 + 同层竞争对手 + 关键数字 + 来源，约 800-1500 token。

## 5. Agent 工具设计（不照搬代码工具命名）

### 5.1 `get_industry_chain_context`（只读查询）

```
name: get_industry_chain_context
description: 查询一只股票在产业链知识图谱里的定位。返回该股所属赛道、技术方向、
  细分环节、上下游、国产化率、毛利率中枢、主要竞争对手，以及这些数据的来源和
  交叉验证状态。分析个股或行业前应先调用本工具建立产业链视角。图谱里没有该股
  时返回空，可用 draft_industry_chain_update 补建。
params: { code: "股票代码，如 300308.SZ / 600519.SH / AAPL" }
```

### 5.2 `draft_industry_chain_update`（起草待审变更）

```
name: draft_industry_chain_update
description: 起草一次产业链图谱更新（不会直接生效，需人工在 /industry-chain 页面
  采纳）。可更新已有节点的字段，或提议新建节点。每个字段变更需附来源。用于处理
  "更新中际旭创最新财报""补建光芯片环节国产化率"这类自然语言更新请求。
params: {
  node_id?: "目标节点（新建则留空）",
  is_new_node?: bool,
  new_node_parent?: "新建节点的父节点 id 或名称",
  new_node_name?: "新建节点名",
  new_node_type?: "track|segment|link|stock",
  new_node_code?: "个股代码（stock 类型）",
  fields: { 要更新的字段名: 新值 },
  sources: [{ source_type, title, publisher, url, cited_text }],
  rationale: "为什么要这样更新"
}
```

工具命名按产业链"自然思维动作"设计（查定位 / 起草更新），不照搬 codegraph 的 search/node/trace 命名。

## 6. AI 主动调用引导机制（D5 三重，独立设计点）

用户明确强调"工具造好 AI 也不会自然用"。三重保障：

1. **工具 description 引导**：两个工具的 description 都明写"分析前先调用"。
2. **Skill description 常驻系统提示**：`industry-chain` skill 的 description 进 `get_descriptions()` → 系统提示常驻（context.py:146），比工具描述更显眼，AI 更容易想起。
3. **自动注入钩子**（最强）：`build_messages` 检测用户消息里的股票代码，若图谱有该股，自动前置 `<industry-chain-context>` 块。AI **不需要想起**，上下文已在那。失败静默降级。

三重叠加，覆盖"AI 想不起来用"的失败模式。第三重是兜底，前两重是主动。

## 7. 注入内容范围（D6）

`GET /industry-chain/context` 和自动注入钩子返回的内容范围：
- 该股直接所属节点（环节）的当前版本：概要 + 国产化率 + 毛利率中枢 + 技术趋势
- 父链路（赛道 → 技术方向 → 该环节）的概要
- 同层主要竞争对手名单（同 parent 下的 stock 节点）
- 该股专属：财务摘要 + 经营指标 + 客户结构
- 来源 + validation_status（disputed 附冲突说明）

约 800-1500 token。不注入兄弟环节细节、不注入全赛道（需要时 AI 调 `get_industry_chain_context` 深挖）。

## 8. 影响面评估（CodeGraph 阶段二产出）

> 基于 CodeGraph 全 AST 扫描（1095 文件 / 15101 节点 / 29370 边）。所有调用链、影响面均实测，非假设。

### 8.1 改动点的上下游依赖图（CodeGraph 实测）

```
                          ┌─ agent/api_server.py (FastAPI app)
                          │   require_auth:651 ← require_local_or_auth:854 (唯一调用者)
                          │   +register_industry_chain_routes(app, require_auth)  [新增 2 行]
                          ▼
   /industry-chain/*  路由 [新增, agent/src/api/industry_chain_routes.py]
        │  async def + asyncio.to_thread(store.*)
        ▼
   agent/src/industry_chain/store.py  [新增, 镜像 goal/store.py 范式]
     IndustryChainStore (单连接 + _synchronized + WAL + PRAGMA user_version)
        │  get_stock_context(code) → 走 _code_index_cache 内存映射
        ▼
   ~/.vibe-trading/industry_chain.db  (SQLite, 用户可直接打开)
        ▲
        │  draft_change / accept_change
   agent/src/tools/industry_chain_draft_tool.py  [新增, BaseTool 子类]
   agent/src/tools/industry_chain_query_tool.py  [新增, BaseTool 子类]
        │  ↑ BaseTool.__subclasses__() 自动发现 (tools/__init__.py:33 _discover_subclasses)
        │  ↑ build_registry() 调用者含 mcp_server.py:95 _get_registry
        │    → 新工具自动暴露给 MCP 客户端 (额外收益, 非风险)
        ▼
   agent/src/agent/context.py:152 build_messages  [改: +自动注入钩子]
        │  镜像 <recalled-memories> 的 try/except 静默降级模式
        │  正则命中已知 code → store.get_stock_context → 前置 <industry-chain-context> 块
        │  build_messages 唯一调用者: AgentLoop.run (loop.py:470)
        ▼
   JSON 200 → frontend/src/lib/api.ts getIndustryChain*()  [新增方法]
        ▼
   frontend/src/pages/IndustryChain.tsx  [新增]
        └─ 挂载于 router.tsx +1 路由 / Layout.tsx 侧边栏 +1 项
```

### 8.2 新增文件

- 后端：`agent/src/industry_chain/__init__.py`、`store.py`、`models.py`、`test_store.py`、`seed.py`
- 后端：`agent/src/api/industry_chain_routes.py`、`test_industry_chain_routes.py`
- 工具：`agent/src/tools/industry_chain_query_tool.py`、`industry_chain_draft_tool.py`、对应测试
- Skill：`agent/src/skills/industry-chain/SKILL.md`
- 前端：`frontend/src/pages/IndustryChain.tsx` + `__tests__/IndustryChain.test.tsx`、`types/industryChain.ts`
- 测试：`agent/tests/test_industry_chain_auto_inject.py`

### 8.3 修改文件（最小侵入）

| 文件 | 改动 | 侵入度 |
|------|------|--------|
| `agent/api_server.py` | +2 行注册 `register_industry_chain_routes` | 极低（镜像 portfolio 注册） |
| `agent/src/agent/context.py` | `build_messages` +自动注入钩子（一段 try/except，镜像现有 recalled-memories） | **中（核心路径，见 8.4 R1）** |
| `frontend/src/router.tsx` | +1 路由 | 极低 |
| `frontend/src/components/layout/Layout.tsx` | NAV +1 项 | 极低 |
| `frontend/src/lib/api.ts` | +若干方法 | 极低 |
| `frontend/src/i18n/index.ts` | +键 | 极低 |

### 8.4 高风险点与缓解（CodeGraph 实测影响面）

| # | 风险 | 严重度 | CodeGraph 实测影响面 | 缓解（已纳入 TASKS） |
|---|------|--------|----------------------|----------------------|
| R1 | `build_messages` 改动影响所有 agent 对话 | **P0** | **影响 88 符号**：AgentLoop.run（唯一调用者）、SessionService、CLI `_legacy._run_agent`、swarm `run_worker`、~30 测试。但改动是**附加式**（镜像 recalled-memories try/except，不改 API 签名），风险=钩子抛异常导致回归，非接口变更 | F1：全 try/except 静默降级，绝不抛回；T-reg 跑 `test_agent_goal_context.py`+`test_persistent_memory.py` 回归基线；T6 三态测试 |
| R2 | SQLite 并发写 | P2 | store 仅本进程内调用（FastAPI 单进程 asyncio+to_thread） | 镜像 goal/store `_synchronized`+`_lock`+WAL（A2） |
| R3 | 股票代码正则误判 | P2 | `build_messages` 每次对话调用 | F2：仅命中 store 已知 code 集合才注入；T-regex 三 case（日期/价格/真股票） |
| R4 | 自动注入拖慢首 token | P2 | 每次 `build_messages` | F3/A1：`_code_index_cache` 内存映射（试点 <1KB），无命中零 DB IO；`idx_nodes_code` 索引 <5ms |
| R5 | AI 起草脏数据污染正式表 | **P0** | draft_tool → store.draft_change | D4：草稿只进 `pending_changes`，accept 才写 `node_versions`；F4 字段白名单校验 |
| R6 | 前端树卡顿 | P3 | 试点 ~30 节点 | F7：试点不虚拟化，>200 再加 |
| R7 | 新工具自动暴露给 MCP 客户端 | P3 | `build_registry` 调用者含 `mcp_server.py:95` | 收益非风险：query 工具可被外部 MCP 调用；draft 工具是写操作，依赖 agent 层权限（与 manage_portfolio 同级） |
| R8 | accept 事务半成品 | P1 | store.accept_change 三步 | F5/T-tx：单连接事务 + 中途失败回滚测试 |

### 8.5 关键架构核查（CodeGraph + 源码，高置信度）

- `[P0]` (conf 10/10) `agent/src/agent/context.py:152 build_messages` — 自动注入镜像同文件 `find_relevant` 的 try/except 静默降级模式（context.py:184 `except Exception as exc: logger.debug(...)`）。系统提示保持 cacheable（注入在 user message，非 system prompt）。**唯一调用者** `AgentLoop.run` (loop.py:470)。
- `[OK]` (conf 10/10) `agent/src/tools/__init__.py:33 _discover_subclasses` — `BaseTool.__subclasses__()` 自动发现，新工具放 `src/tools/` 即自动注册到 `build_registry()`。
- `[OK]` (conf 9/10) `build_registry` 调用者含 `agent/mcp_server.py:95 _get_registry` — 新工具自动暴露给 MCP 客户端。
- `[OK]` (conf 10/10) `agent/src/goal/store.py:90-118` — `_synchronized`+`_lock`+WAL+`PRAGMA user_version` 迁移范式，本模块 `IndustryChainStore` 完全镜像。
- `[OK]` (conf 9/10) `agent/api_server.py:651 require_auth` ← `:854 require_local_or_auth`（唯一调用者）— 路由注册镜像 `register_alpha_routes(app, require_auth=None)` sys.modules 回退模式。
- `[OK]` (conf 9/10) `agent/src/api/portfolio_routes.py` — 现有路由范式基准（`asyncio.to_thread` + 具名异常 + `_redact_text`），本模块镜像。
- `[OK]` (conf 9/10) `frontend/src/components/layout/Layout.tsx:18 NAV` + `router.tsx` lazy import — 前端集成范式基准。

### 8.6 不触碰（隔离边界，CodeGraph 确认零交叉）

- `agent/src/trading/` 连接器、`agent/src/live/` enforcement/reconcile、`/live/*` 路由、backtest、swarm runtime、sessions、alpha、portfolio 现有功能 —— 与本模块无共享 module、无调用交叉
- `vibe_trading/` 孤岛（已废弃，`package-dir=agent` 导致不可导入）

### 8.7 并行化策略（worktree）

后端 store+routes+tools+context 钩子（Lane A）与前端页面+路由+Layout+api.ts+i18n（Lane B）**模块正交**：
- Lane A 改：`industry_chain/`、`api/industry_chain_routes.py`、`tools/industry_chain_*`、`agent/context.py`、`api_server.py`
- Lane B 改：`frontend/src/pages/IndustryChain.tsx`、`router.tsx`、`Layout.tsx`、`lib/api.ts`、`i18n`
- **无文件重叠**，可两 worktree 并行；合并后做集成验证（T13/T15）
- 唯一顺序约束：Lane A 的 API 契约（§4）先定，Lane B 的 `api.ts` 方法签名对齐

### 8.8 回滚

无破坏性变更、无 DB migration（新建库）、无配置变更。回滚 = `git revert` PR，可逆性 5/5。SQLite 文件在 `~/.vibe-trading/industry_chain.db`，删库即清空，不影响主应用。

### 8.4 不触碰（隔离边界）

- `agent/src/trading/`、`/live/*`、backtest、swarm、sessions、alpha、portfolio 现有功能
- `vibe_trading/` 孤岛（已废弃，不接入）

### 8.5 回滚

无破坏性变更。回滚 = `git revert` PR。SQLite 文件在 `~/.vibe-trading/`，删库即清空，不影响主应用。

## 9. 测试策略（覆盖率 ≥80%）

| 层 | 文件 | 覆盖 |
|----|------|------|
| Store 单元 | `agent/src/industry_chain/test_store.py` | CRUD、版本快照、当前指针、来源绑定、pending 变更 accept/reject、并发写、schema 迁移 |
| 路由单元 | `agent/src/api/test_industry_chain_routes.py` | 全部端点、auth 依赖、tree/context/pending 三大流、错误处理 |
| 工具单元 | `agent/src/tools/test_industry_chain_*_tool.py` | 查询返回结构、起草写 pending、缺图谱降级 |
| 自动注入 | `agent/tests/test_industry_chain_auto_inject.py` | context.py build_messages 三态（无图谱/无该股/有该股）、正则匹配、静默降级 |
| 前端单元 | `frontend/src/pages/__tests__/IndustryChain.test.tsx` | 树渲染、节点编辑、待审区 accept/reject、loading/error/empty |
| 集成 | `/qa` 端到端 | 真实浏览器：浏览树、编辑节点、AI 起草→采纳全流程 |

## 10. 未涉及范围（后续）

- 全市场赛道扩展（试点跑通后再做）
- 图形化连线视图（D8 选树导航）
- 字段级版本（D2 选节点级）
- AI 自动交叉验证（D3 选人工状态切换）
- 多账户/多用户协作

## 11. CEO 评审结论（/plan-ceo-review，HOLD SCOPE）

**模式**: HOLD SCOPE（8 轮 office-hours 澄清已锁定边界，不扩张不缩减）
**实现路径**: APPROACH A — 全量三形态并行（一个 PR 交付图谱+可视化+AI起草+自动注入）

### 11.1 前提核查
- 需求成立、不重复 sector-rotation（字段语义不同）✓
- 复用 goal/store / context.build_messages / portfolio_routes / BaseTool / 数据源工具，无平行重建 ✓
- 三个产出形态优先级澄清：**第三形态（自动注入）是核心价值**，可视化+AI起草是维护手段；但用户选 A 全量并行，一次跑通完整闭环

### 11.2 HOLD SCOPE 加固发现（已纳入 TASKS）

| # | 发现 | 严重度 | 落地（纳入 DESIGN/TASKS） |
|---|------|--------|--------------------------|
| F1 | context.py 自动注入必须 zero-regression（核心对话路径） | P0 | 钩子全 try/except 静默降级；无 DB/无该股/查询失败三态测试；回归测试"注入失败不破坏 recalled-memories"（T6） |
| F2 | 股票代码正则误判（6 位数字≠股票） | P1 | 仅当带 .SH/.SZ/.BJ 后缀，或纯 6 位数字且命中 store 已知 code 集合时才注入；港股/美股单独规则（T6） |
| F3 | 自动注入拖慢首 token | P1 | 启动加载 code→node_id 内存映射（试点 <1KB），正则命中内存集合才查 DB 详情，无命中零 IO（T6） |
| F4 | AI 起草字段校验（任意 JSON 风险） | P1 | fields 白名单校验（仅 schema 字段+extra），拒绝未知字段；sources 必填且 source_type 枚举校验（T4） |
| F5 | pending 采纳事务性 | P2 | accept 三步（写 version+更新指针+标 accepted）单连接事务，失败回滚（T1） |
| F6 | 删除节点级联孤儿 | P2 | 有子节点拒绝删除（409 + 提示先删子），MVP 不级联（T1/T2） |
| F7 | 前端树虚拟化时机 | P2 | 试点不虚拟化，节点>200 再加，写入 TASKS 避免过度工程（T9） |
| F8 | 种子数据来源合规 | P1 | seed.py 也走 sources 表，source_type 枚举，不裸填（T7） |
| F9 | validation_status 可观测 | P2 | get_stock_context 对 disputed 字段附各来源冲突值（T1/T3） |
| F10 | context.py 改动测试+回归 | P1 | T6 测试独立完整；跑现有 agent 对话测试确保无回归（T13） |

### 11.3 关键判断
核心价值是第三形态（自动注入），但用户选择全量并行以一次跑通完整闭环、验证最充分。风险集中在 context.py 核心路径改动（F1），靠 try/except 静默降级 + 三态测试 + 回归测试兜住。其余为数据完整性与 UX 加固。

## 12. Eng 评审结论（/plan-eng-review，HOLD SCOPE）

**模式**: HOLD SCOPE（与 CEO 评审一致）
**架构核查**: 已读源码确认 `context.py:152 build_messages` 注入点（镜像 `<recalled-memories>` try/except 块）、`goal/store.py` 单连接+`_synchronized`+WAL+`PRAGMA user_version` 迁移范式、`tools/__init__.py` `BaseTool.__subclasses__()` 自动发现（新工具放 src/tools/ 自动注册）。

### 12.1 §1 架构发现

| # | 发现 | 严重度 | 落地 |
|---|------|--------|------|
| A1 | 自动注入的 code→node_id 缓存位置（ContextBuilder 每次 run 都 new） | P0 | store 自带模块级 `_code_index_cache` 单例，ContextBuilder 只调 `store.get_stock_context(code)`，store 内部决定走缓存（T1/T6） |
| A2 | store 连接生命周期（跨进程？） | P1 | 仓库是单进程 asyncio+to_thread，镜像 goal/store 单连接+锁即可，不需连接池（T1） |
| A3 | node_versions 无限增长 | P1 | DESIGN §10 声明"不自动清理，人工按需删旧版本"（历史回溯是硬约束，非 bug） |
| A4 | 数值字段 TEXT 无法结构化筛选 | P2 | 试点不需要筛选（8-12 股手动浏览），TEXT 保留溯源上下文是对的；结构化筛选列后续（§10） |

### 12.2 §2 代码质量（DRY）
- Q1: 本模块无外部数据源归一化需求（数据全自写 schema），不涉及 portfolio_routes `_normalize_row` DRY 问题 ✓
- Q2: query_tool/draft_tool 通过 `IndustryChainStore` 单例访问，工具不直接开 sqlite3 连接（钉死 TASKS T3/T4）✓

### 12.3 §3 测试发现

| # | 发现 | 严重度 | 落地 |
|---|------|--------|------|
| T-reg | context.py 回归基线（test_agent_goal_context.py / test_persistent_memory.py） | P0 | T13 显式跑这两个文件确保 recalled-memories 注入不破坏（F10） |
| T-tx | store 事务测试：accept 中途失败无半成品状态 | P1 | T1 加 case：写 version 后、更新指针前模拟异常 → 验证回滚（F5） |
| T-regex | 自动注入正则边界：8 位日期 / 价格 / 真股票三 case | P1 | T6 加 case：仅真股票代码注入（F1/F2） |
| T-seed | seed() 幂等：二次运行不报错不重复 | P2 | T7 加 case（F8） |

### 12.4 §4 性能
- P1: 自动注入首 token —— store 走 `idx_nodes_code` 索引 <5ms，code 内存映射 <1KB（试点 12 股），可接受（F3）
- P2: 前端树 —— 试点不虚拟化，>200 节点再加（F7）

### 12.5 关键架构核查（高置信度，均读源码确认）
- `[P0]` context.py:152 `build_messages` — 自动注入镜像 `<recalled-memories>` 的 try/except 静默降级模式，系统提示保持 cacheable ✓
- `[OK]` tools/__init__.py:33 `_discover_subclasses` — `BaseTool.__subclasses__()` 自动发现，新工具放 src/tools/ 即自动注册 ✓
- `[OK]` goal/store.py:90-118 — `_synchronized`+`_lock`+WAL+`PRAGMA user_version` 迁移范式，本模块镜像 ✓

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Office Hours | `/office-hours` | 需求澄清 | 1 | clean | 8 轮苏格拉底澄清，8 项决策全选推荐，需求成立不重复 sector-rotation |
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | clean | mode: HOLD_SCOPE, APPROACH A 全量三形态并行；10 项加固发现 F1-F10 纳入 TASKS |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | clean | 4 项架构发现 A1-A4 + 4 项测试发现 T-reg/T-tx/T-regex/T-seed 纳入 TASKS；0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | pending | UI scope present (树导航+编辑面板) — optional, 阶段四 /qa 覆盖 |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | skipped | outside voice deferred (non-blocking) |

- **VERDICT:** CEO + ENG CLEARED — ready to implement. Eng review is the required gate and is CLEAR.
- **NOT in scope:** 全市场赛道扩展、图形化连线视图、字段级版本、AI 自动交叉验证、多账户协作（均见 §10）。
- **What already exists:** `goal/store.py` SQLite 范式、`context.build_messages` 注入模式、`portfolio_routes` 路由模式、`BaseTool` 自动发现、`research_reports/sec_filings/financial_statements/web_reader/doc_reader` 数据源工具、`Layout.tsx` 侧边栏、`lib/api.ts` request。
- **Dream state delta:** 铺设"产业链知识中台"第一块砖，分析任意个股自动带产业链视角，图谱持续 AI 起草+人工采纳滚动更新。
- **Failure modes:** context.py 核心路径侵入(已解,try/except 静默降级+三态+回归测试) / 正则误判(已解,命中已知 code 集合) / 首 token 延迟(已解,内存映射+索引) / AI 脏数据(已解,pending 待审+字段白名单) / 事务半成品(已解,单连接事务+回滚测试) / 删节点孤儿(已解,有子拒绝) — 0 critical gaps。
- **Core value sequencing:** 第三形态（自动注入）是真正解决痛点的核心；可视化编辑+AI 起草是维护手段。用户选 APPROACH A 一次跑通完整闭环。

NO UNRESOLVED DECISIONS
