# 产业链知识库 — 任务列表

> 对应 DESIGN.md。试点赛道：AI 算力产业链（CPO/OCS/光芯片/PCB + 8-12 只龙头股）。
> 执行阶段（阶段三）会用 `/writing-plans` 把每个任务再拆成 2-5 分钟微任务 + 完整代码 + 验证命令。

## 任务总览

| ID | 任务 | 优先级 | 依赖 | 阶段 |
|----|------|--------|------|------|
| T1 | Store：`industry_chain/store.py` SQLite schema + CRUD + 版本快照 + pending（TDD 先写测试） | P0 | — | 执行 |
| T2 | 路由：`api/industry_chain_routes.py` 全端点 + 注册到 api_server | P0 | T1 | 执行 |
| T3 | 工具：`industry_chain_query_tool.py`（只读查询） | P0 | T1 | 执行 |
| T4 | 工具：`industry_chain_draft_tool.py`（起草 pending） | P0 | T1 | 执行 |
| T5 | Skill：`skills/industry-chain/SKILL.md`（description 注入引导） | P0 | T3 | 执行 |
| T6 | 自动注入钩子：`context.py build_messages` + 三态测试 | P0 | T1 | 执行 |
| T7 | 种子数据：`industry_chain/seed.py` AI 算力产业链 4 方向 + 8-12 股 | P0 | T1 | 执行 |
| T8 | 前端：`types/industryChain.ts` + `lib/api.ts` 方法 | P0 | T2 | 执行 |
| T9 | 前端：`pages/IndustryChain.tsx` 树导航 + 节点编辑面板 | P0 | T8 | 执行 |
| T10 | 前端：待审区面板（accept/reject） | P0 | T9 | 执行 |
| T11 | 前端：`router.tsx` 路由 + `Layout.tsx` 侧边栏 + i18n | P0 | T9 | 执行 |
| T12 | 前端单元测试 `IndustryChain.test.tsx`（TDD 先写） | P0 | T9 | 执行 |
| T13 | 覆盖率核验（≥80%）+ 全量测试 | P0 | T1-T12 | 验收 |
| T14 | Staff Engineer 代码审查（/review） | P0 | T13 | 验收 |
| T15 | 端到端 QA（/qa） | P0 | T14 | 验收 |
| T16 | 发布 PR（/ship） | P0 | T15 | 发布 |

---

### T1: Store — `agent/src/industry_chain/store.py`（TDD）

镜像 `agent/src/goal/store.py` 的连接/锁/迁移模式（`_synchronized`+`_lock`+WAL+`PRAGMA user_version`）。DB：`~/.vibe-trading/industry_chain.db`，env `VIBE_TRADING_INDUSTRY_CHAIN_DB_PATH`。

**先写测试** `agent/src/industry_chain/test_store.py`：
- schema 自动迁移（首次建库、二次幂等，`PRAGMA user_version`）
- `create_node` / `get_node` / `list_children` / `update_node`（写新版本 + 更新 node_current 指针）
- `get_node_current`（O(1) 取当前版本）
- `list_versions`（历史回溯）
- `add_source` / `list_sources(version_id)`
- `draft_change` / `list_pending` / `accept_change` / `reject_change`
- **A1**：`get_stock_context(code)` 走模块级 `_code_index_cache`（首次查询加载，命中内存才查 DB 详情）
- **F5/T-tx**：`accept_change` 单连接事务 —— 测试 accept 中途失败（写 version 后、更新指针前抛异常）→ 验证无半成品状态、pending 仍 draft
- **F6**：`delete_node` 有子节点时拒绝（返回错误，不级联）
- **F9**：`get_stock_context` 对 `validation_status=disputed` 字段附各来源冲突值
- 并发写：双线程同时 update，`_synchronized` 保证不 corrupt
- WAL 模式开启（`PRAGMA journal_mode=WAL`）

**设计约束**：store 持有单连接 + 锁（A2）；不自动清理 node_versions（A3，历史回溯硬约束）；数值字段 TEXT（A4，保留溯源上下文）。

**验证**：`cd agent && python -m pytest src/industry_chain/test_store.py -v`（先红后绿）

---

### T2: 路由 — `agent/src/api/industry_chain_routes.py`

导出 `register_industry_chain_routes(app, require_auth=None)`（镜像 alpha_routes sys.modules 回退）。端点见 DESIGN §4。写操作走 `asyncio.to_thread`。具名异常捕获。

**测试** `agent/src/api/test_industry_chain_routes.py`：全端点、auth 依赖、tree/context/pending 三流、错误降级。

**注册** `agent/api_server.py`：+`from src.api.industry_chain_routes import register_industry_chain_routes` + `register_industry_chain_routes(app, require_auth)`。

**验证**：启动后 `curl -H "Authorization: Bearer $KEY" http://localhost:8000/industry-chain/tree` 返回 JSON。

---

### T3: 工具 — `industry_chain_query_tool.py`

`IndustryChainQueryTool(BaseTool)`，name=`get_industry_chain_context`，只读。调 `store.get_stock_context(code)`。DESIGN §5.1。

**测试**：查询返回结构、缺图谱降级返回空、未知 code 处理。

---

### T4: 工具 — `industry_chain_draft_tool.py`

`IndustryChainDraftTool(BaseTool)`，name=`draft_industry_chain_update`，非只读。调 `store.draft_change(...)`。DESIGN §5.2。**Q2：工具不持有 sqlite 连接，只调 store 方法。**

**测试**：起草写 pending、**F4 字段白名单校验**（仅 schema 字段+extra，拒绝未知字段）、**F4 sources 必填且 source_type 枚举校验**、新建节点流程。

---

### T5: Skill — `agent/src/skills/industry-chain/SKILL.md`

frontmatter `description` 明写"分析个股/行业前先用 get_industry_chain_context 查产业链定位"。body 详述何时查、何时起草更新、人工审核流程。

**验证**：`SkillsLoader` 能加载，`get_descriptions()` 含该 skill。

---

### T6: 自动注入钩子 — `agent/src/agent/context.py`

在 `build_messages`（context.py:152）镜像 `<recalled-memories>` 的 try/except 静默降级模式：正则检测 A 股/港股/美股代码 → 查 `store.get_stock_context` → 前置 `<industry-chain-context>` 块。**F1：全 try/except 静默降级，绝不抛回调用方。**

**F2/T-regex**：正则规则 —— 仅当带 `.SH/.SZ/.BJ` 后缀，或纯 6 位数字且命中 store 已知 code 集合时才注入；港股（5 位 `.HK`）、美股 ticker（2-5 大写字母）单独规则。测试三 case：8 位日期 `20240301`（不注入）/ 价格 `12.50`（不注入）/ `300308.SZ`（注入）。

**F3/A1**：store 走 `_code_index_cache` 内存映射，无命中零 DB IO。

**测试** `agent/tests/test_industry_chain_auto_inject.py`：
- **F1 三态**：无 DB / DB 有但无该股 / DB 有该股
- **T-regex 边界**：上述三 case
- **F1 回归**：注入失败不破坏现有 `<recalled-memories>` 行为
- 静默降级（store 抛异常 → 返回原始 user_message）

---

### T7: 种子数据 — `agent/src/industry_chain/seed.py`

AI 算力产业链：赛道 → CPO/OCS/光芯片/PCB 四方向 → 每方向 1-2 细分环节 → 8-12 只龙头股（中际旭创/新易盛/天孚通信/沪电股份/生益科技等）。每节点带概要 + 关键字段。提供 `seed()` 幂等函数 + CLI 入口。

**F8/T-seed**：种子数据也走 sources 表，source_type 枚举（`annual_report`/`broker_report` 等），不裸填无来源。`seed()` 幂等 —— 测试二次运行不报错不重复。

**验证**：`python -m src.industry_chain.seed` 后 `get_industry_chain_context 300308.SZ` 返回中际旭创的 CPO 定位。

---

### T8: 前端类型 + API 客户端

`frontend/src/types/industryChain.ts`：`ChainNode`/`NodeVersion`/`Source`/`PendingChange`/`ChainTree` 类型。
`frontend/src/lib/api.ts`：+`getIndustryChainTree`/`getNode`/`createNode`/`updateNode`/`deleteNode`/`getPendingChanges`/`acceptPendingChange`/`rejectPendingChange`/`getIndustryChainContext`。

**验证**：`cd frontend && npx tsc --noEmit`

---

### T9: 前端页面 — `pages/IndustryChain.tsx`

左树导航（赛道→方向→环节→个股，可折叠）+ 右编辑面板（字段表单 + 解读文本框 + 来源列表 + 版本历史下拉）。状态机 loading/error/empty/ready。

---

### T10: 前端待审区

页面内 tab/抽屉：列出 pending_changes，每条可 accept/reject，accept 后刷新树。

---

### T11: 前端集成

`router.tsx` +`/industry-chain` 路由；`Layout.tsx` NAV +`{ to: "/industry-chain", icon: Network, label: t('layout.industryChain') }`；`i18n/index.ts` +中英键。

---

### T12: 前端单元测试（TDD 先写）

`frontend/src/pages/__tests__/IndustryChain.test.tsx`：树渲染、选中节点加载详情、编辑保存、待审区 accept/reject、loading/error/empty、刷新。

**验证**：`cd frontend && npx vitest run src/pages/__tests__/IndustryChain.test.tsx`

---

### T13: 覆盖率 + 全量测试

```bash
cd agent && python -m pytest src/industry_chain/ src/api/test_industry_chain_routes.py src/tools/test_industry_chain_*_tool.py tests/test_industry_chain_auto_inject.py --cov=src.industry_chain --cov=src.api.industry_chain_routes --cov-report=term-missing
cd ../frontend && npx vitest run --coverage
```
目标：产业链相关文件行覆盖率 ≥80%。

**T-reg（F10）**：额外跑回归基线，确保 context.py 改动不破坏现有注入：
```bash
cd agent && python -m pytest tests/test_agent_goal_context.py tests/test_persistent_memory.py -v
```

---

### T14: 代码审查（/review）
### T15: 端到端 QA（/qa）
### T16: 发布（/ship）

详见工作流阶段四。
