# CHANGELOG.md — 多 Agent 协作变更记录

> 本文件用于在不同 Agent session 之间同步“已经做了什么、为什么做、接下来可能做什么”。
>
> **强制要求**：每次完成任何开发相关操作后，都要在本文件中追加一条记录。

## 记录格式

```md
## YYYY-MM-DD

### [类型] 简短标题
- 文件：涉及的文件路径
- 变更：做了什么
- 原因：为什么这样改（可选）
- 后续：下一步或注意事项（可选）
```

## 2026-04-14

### [implementation] 完成 P1.6 应用调度层
- 文件：`src/app.py`、`src/router/action_router.py`、`tests/test_action_router.py`、`tests/test_app.py`
- 变更：实现外部循环的最小应用层封装、session 自动创建、启动恢复检查入口、`session_updates` 白名单校验、`ask_user`/`recommend`/`dispatch_product_search`/`onboard_user` 的路由行为，以及产品搜索后的 `pending_research_result`、`candidate_products`、`recommendation_round` 与 `pending_profile_updates` 后处理。
- 原因：按 `TASKS.md` 落地 Phase 1 的应用调度层主路径，使主 Agent 与研究 Agent 可以通过统一的 Action Router 串联起来。
- 后续：P1.7 接入正式 `SessionContextProvider` 后，可替换 `app.py` 里的临时 context 组装逻辑；`dispatch_category_research` 在 P2.2 接通真实实现。

### [implementation] 完成 P1.4-P1.5 Agent 基础定义
- 文件：`src/agents/main_agent.py`、`src/agents/research_agent.py`、`src/agents/tools.py`、`src/agents/prompts.py`、`tests/test_main_agent.py`、`tests/test_research_agent.py`
- 变更：实现主 Agent 的创建与运行封装，固定 `DecisionOutput` 结构化输出且不注册工具；实现研究 Agent 的 Tavily 搜索工具、产品搜索 prompt 渲染、payload 校验、基于 `global_profile.location` 的搜索语言注入，以及 `dispatch_product_search` 的异步执行入口。
- 原因：继续按 `TASKS.md` 落地 Phase 1 的主 Agent 与研究 Agent 能力，同时保持 prompt 文本以 `docs/PROMPTS.md` 为单一来源。
- 后续：P1.6 接入应用调度层后，再把 `execute_research()` 和主 Agent 封装串到外部循环与 Action Router 中。

### [implementation] 完成 P1.1-P1.3 基础落地
- 文件：`pyproject.toml`、`.gitignore`、`src/`、`tests/`、`data/`、`docs/CHANGELOG.md`
- 变更：新增 Phase 1 所需最小目录骨架与包初始化；补充 `pydantic`、`python-dotenv`、`tavily-python` 依赖；实现 `DecisionOutput` / `CategoryResearchOutput` / `ProductSearchOutput` 相关模型；实现仅覆盖 session 的 `DocumentStore`；新增对应单元测试。
- 原因：按 `TASKS.md` 的 P1.1-P1.3 先落地最小可运行基础设施，为后续 Agent、调度层和 CLI 实现提供稳定接口。
- 后续：P1.4 起继续复用这些模型和 `DocumentStore`，`apply_pending_profile_updates()` 在 Phase 2 再扩展为真实恢复逻辑。

### [docs] 补强 AGENTS.md 的开发与协作约束
- 文件：`docs/AGENTS.md`
- 变更：补充了当前项目状态、目标结构与现状区分、文档权威顺序、文档冲突处理、`uv` 环境与常用命令、变更同步清单、最小验证标准，以及“每次操作完成后必须记录 CHANGELOG”的协作规则。
- 原因：让 `AGENTS.md` 从“概念型指南”升级为“可执行的多 Agent 入口文档”。
- 后续：后续所有文档修改、代码实现、测试进展都应继续追加记录到本文件。

### [docs] 初始化 CHANGELOG 规范
- 文件：`docs/CHANGELOG.md`
- 变更：将原来的单行备注整理为正式 changelog 模板，并加入本次修改记录。
- 原因：为不同 Agent session 提供稳定、可追踪的协作交接面。
