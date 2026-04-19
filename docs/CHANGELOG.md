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

## 2026-04-19

### [docs] 重写 README 为公开展示版项目说明
- 文件：`README.md`、`docs/CHANGELOG.md`
- 变更：
  1. 将原本偏运行配置说明的 README 重写为适合公开展示的中文项目简介
  2. 补充产品定位、1+1 Agent 架构、Agent harness / 控制层、文档化记忆、真实项目结构、技术栈与当前进度说明
  3. 明确项目仍在迭代中，并补充后续 Web UI 方向，但不把内部 Phase 规划直接暴露到 README
- 原因：当前需要对外展示仓库，用于求职场景；README 需要同时体现产品思维、架构设计能力和当前工程落地状态，而不是仅保留内部开发视角的运行说明

## 2026-04-17

### [implementation] 代码落地 Tavily-only 研究链路与 OpenAI-compatible env 合同
- 文件：`src/utils/runtime_config.py`、`src/agents/main_agent.py`、`src/agents/research_agent.py`、`src/agents/tools.py`、`src/router/action_router.py`、`src/prompts/main_agent_system.txt`、`src/prompts/product_search.txt`、`src/prompts/category_research.txt`、`README.md`、`tests/test_main_agent.py`、`tests/test_research_agent.py`、`tests/test_action_router.py`、`tests/test_prompts.py`、`tests/test_tools.py`、`tests/test_env_example.py`、`docs/CHANGELOG.md`
- 变更：
  1. 新增共享运行时配置 helper，按“Agent 专属 > 共享默认 > 代码默认值”解析 OpenAI-compatible endpoint/key/model，并拒绝半配置的 Agent 专属覆盖
  2. 主 Agent / 研究 Agent client factory 改为读取 `LLM_*`、`MAIN_AGENT_*`、`RESEARCH_AGENT_*`，不再依赖 `SHOPPING_*` 变量
  3. 研究 Agent client 显式加入 function invocation guardrails，保持“一次 dispatch = 一次临时 research run”的运行模型
  4. Tavily `search_web` 增加每次结果数 clamp、URL/文本去重和极长 `raw_content` 保护，仍保持广度优先，不做摘要重写
  5. `ActionRouter` 对 `search_meta.retry_count` / `search_meta.search_expanded` 做应用层规范化，确保 `error_state` 和后续消费使用 authoritative 值
  6. runtime prompt、README 和回归测试同步到 Tavily-only + 高层 `research_brief` + 薄护栏 的新口径
- 原因：把上一轮已确认的文档方案真正落到实现上，消除文档、prompt、测试与运行时代码之间的配置和行为漂移
- 后续：如后面要进一步开放 research budget env，可在当前 guardrails 基础上继续演进；本轮先保持代码默认值

### [docs] 收口研究搜索口径为 Tavily-only 并补齐 env 合同
- 文件：`docs/ARCHITECTURE.md`、`docs/SPEC.md`、`docs/INTERFACES.md`、`docs/PROMPTS.md`、`docs/TESTING.md`、`docs/TASKS.md`、`.env.example`、`docs/CHANGELOG.md`
- 变更：
  1. 将研究搜索方案统一收口为 Tavily 单工具口径，删除或替换文档中会造成歧义的额外搜索 backend 描述
  2. 明确一次 `dispatch_*` 对应一次临时 research run：run 内不拆分多个子 Agent session，完成后销毁，不长期保留子 Agent 中间工具历史
  3. 将 LLM 配置统一为 OpenAI-compatible env 合同，采用“Agent 专属配置 > 共享默认配置 > 代码默认值”的优先级，并新增 `.env.example`
  4. 收紧 `search_meta` 的 ownership 说明：`retry_count` / `search_expanded` 由应用层规范化，研究 Agent 负责提供结构化结果而非唯一 telemetry source
  5. 将研究策略文档调整为“增强版方案 A”：广度优先、同次 run 内积极多轮搜索、系统层只加薄护栏，不引入长期子 Agent session 或强编排器
- 原因：本轮 review 已确认搜索模式、配置方式和子 Agent 生命周期的目标口径，需要先把开发文档统一，避免后续代码实现继续在架构、prompt 和测试之间漂移
- 后续：运行时代码和 `src/prompts/` 仍需后续同步到本次文档口径；本次提交仅修改文档与示例配置文件

### [refactor] 迁移运行时 prompt 资源到 src/prompts
- 文件：`src/prompts/`、`src/agents/prompts.py`、`tests/test_prompts.py`、`tests/test_main_agent.py`、`tests/test_research_agent.py`、`docs/PROMPTS.md`、`docs/TASKS.md`、`docs/ARCHITECTURE.md`、`docs/TESTING.md`、`docs/INTERFACES.md`、`docs/SPEC.md`、`docs/CHANGELOG.md`
- 变更：
  1. 新增 `src/prompts/main_agent_system.txt`、`category_research.txt`、`product_search.txt` 作为运行时唯一 prompt 资源来源
  2. 重写 `src/agents/prompts.py`，删除对 `docs/PROMPTS.md` 的读取、Markdown 解析与 LRU 缓存，改为直接按文件名读取运行时资源
  3. 新增 prompt loader 专项测试，并补充主 Agent / 研究 Agent 的运行时 prompt 回归断言与模板占位符渲染校验
  4. 收口文档口径，明确 `docs/PROMPTS.md` 仅为开发文档，运行时代码只能读取 `src/prompts/`
- 原因：避免让 docs 参与运行时逻辑，去掉文档结构与代码实现的强耦合，降低 prompt 维护成本

### [docs] 收口 TESTING 1-4 对 phase3 保护链路的覆盖口径
- 文件：`docs/TESTING.md`、`tests/test_action_router.py`、`docs/CHANGELOG.md`
- 变更：
  1. 在 `TESTING.md` 的 3.3/3.4/4.1-4.4 中补充 phase3 已实现但此前未完整写入的关键覆盖项，包括主 Agent 重试与降级、研究 dispatch 重试与降级、日志级别分层、需求挖掘软边界、连续负面反馈提示，以及显式新开会话的恢复路径
  2. 为 `dispatch_category_research` 补充三条回归测试，覆盖“首次失败后重试成功”“连续失败降级”“结构化结果不可解析时降级”，避免该分支继续只靠产品搜索同类用例间接代表
- 原因：本轮 review 发现 `TESTING` 1-4 对 phase3 保护链路的口径不完整，且品类调研失败分支缺少直接自动化回归，需要把文档要求和实际测试面重新对齐

### [implementation] 完成 P3.5 的错误处理与降级
- 文件：`src/app.py`、`src/router/action_router.py`、`src/utils/logger.py`、`tests/test_app.py`、`tests/test_action_router.py`、`docs/CHANGELOG.md`
- 变更：
  1. 为主 Agent 增加应用层重试与降级：LLM/API 调用失败时自动重试 1 次，连续失败后返回“服务暂时不可用”的友好消息；DecisionOutput 解析失败时同样重试 1 次，连续失败后返回保守通用消息
  2. 为研究 dispatch 增加应用层重试与降级：研究执行异常时自动重试 1 次，并在重试时补充 `research_brief` 提示模型更换关键词策略；连续失败或返回不可解析结果时，为产品搜索生成可消费的空结果降级响应，并对品类调研生成不落 knowledge 的空结果交接
  3. 为 `SessionLogger` 增加对 `action_metrics.error` 的 ERROR 识别，确保“降级但不中断”的 turn 也能被稳定记为错误而不是普通 warning
  4. 在 outer loop context 中新增连续负面反馈提示：当 `error_state.consecutive_negative_feedback >= 2` 时，向主 Agent 注入“反思推荐策略并重新锚定需求”的系统标注
  5. 补充回归测试，覆盖主 Agent 重试成功、主 Agent 双次失败降级、研究搜索重试成功、研究搜索双次失败降级、研究结果不可解析降级，以及连续负面反馈提示注入
- 原因：对齐 `docs/TASKS.md` 的 P3.5 与 `SPEC.md §10.2`、`§10.4`、`§13.1` 的要求，保证异常情况下 outer loop 不崩溃且对用户保持透明降级

## 2026-04-16

### [implementation] 完成 P3.4 的 outer-loop 边界保护
- 文件：`src/app.py`、`src/utils/logger.py`、`tests/test_app.py`、`docs/CHANGELOG.md`
- 变更：
  1. 在应用层新增可配置的 `BoundaryConfig`，实现 session 最大轮数、需求挖掘追问轮数、品类调研上限、产品搜索软上限
  2. 在主 Agent 调用前基于 JSONL 日志派生会话活动计数，并将需求挖掘 / 产品搜索的软提示注入 context
  3. 在 outer loop 中拦截第 3 个不同品类的 `dispatch_category_research`，并在达到最大轮数后直接终止继续推进但保留当前 session
  4. 扩展 session logger，对边界事件做 warning / error 归档，便于离线分析
  5. 新增边界保护相关回归测试
- 原因：对齐 `docs/TASKS.md` 中 P3.4 与 `SPEC.md §13.1`、`ARCHITECTURE.md §12.4` 的要求

### [implementation] 完成 P3.2 / P3.3 的研究输出校验与每轮 JSONL 日志
- 文件：`src/agents/research_agent.py`、`src/router/action_router.py`、`src/app.py`、`src/utils/logger.py`、`tests/test_action_router.py`、`tests/test_app.py`、`docs/CHANGELOG.md`
- 变更：
  1. 为研究结果新增应用层额外校验：产品搜索结果允许空列表返回，但会对非空产品的核心字段、价格结构与来源 URL 做 sanity check；品类调研结果会对关键子结构非空做检查
  2. 校验命中时不打断 dispatch 主流程，而是把 warning 追加到 `error_state.validation_warnings`，并自动在研究结果 `notes` 中附加 `[系统校验警告]` 标注
  3. 为 `ActionRouter` 增加 dispatch 结果摘要和研究耗时采集，供日志稳定记录 `search_meta`、产品数、品类调研目标等信息
  4. 新增 `SessionLogger`，在每轮 outer loop 后向 `data/sessions/session_log.jsonl` 追加一条 JSONL，记录时间戳、用户输入、完整 `DecisionOutput`、stage 变化、`next_action` 执行结果、warning 与 error
  5. 补充回归测试，覆盖“研究输出结构缺陷只记 warning 不崩溃”“每轮 turn 产生日志”“staleness 记为 WARNING”“dispatch 错误记为 ERROR”
- 原因：按 `docs/TASKS.md` 收口 P3.2 / P3.3，确保研究输出的结构问题可观测、可降级，同时为后续离线分析与指标统计提供稳定日志来源

### [test] 补齐 4.1-4.3 集成链路的显式覆盖
- 文件：`tests/test_app.py`、`docs/CHANGELOG.md`
- 变更：
  1. 为外部循环补充显式 `ask_user -> dispatch_product_search -> recommend` 集成测试，断言 `pending_research_result` 设置、`candidate_products` 刷新、下一轮消费后清除 pending
  2. 新增应用层测试，覆盖推荐完成时 `pending_profile_updates` 草稿写入
  3. 新增品类调研创建并增量合并 knowledge 的应用层测试
  4. 新增产品搜索空结果链路测试，以及研究执行前校验失败时应用层记录 warning 且不崩溃的测试
- 原因：按 `docs/TESTING.md` 收口 `4.1-4.3` 中此前偏间接或不够显式的集成覆盖，使对应链路在应用层具备清晰回归保护

### [implementation] 完成 P3.1 的研究任务 payload sanity check 收口
- 文件：`src/agents/research_agent.py`、`tests/test_research_agent.py`、`docs/CHANGELOG.md`
- 变更：
  1. 为 `execute_research()` 增加统一的 task-specific payload sanity check 入口，在创建研究 Agent 前校验必填字段、关键字段非空以及基础类型合法性
  2. 收紧 `dispatch_product_search` 的最小约束：`constraints` 不能为空对象，`key_requirements` 必须为非空字符串列表；同时将 `exclusions` 调整为真正可选，仅在提供时校验为字符串列表
  3. 为非法 payload 和非法 `task_type` 增加错误日志记录，并在校验失败时直接拒绝执行研究任务
  4. 补充研究侧单测，覆盖可选字段缺省、空关键列表、非法 task type，以及“非法 payload 不创建研究 Agent”的拒绝路径
- 原因：按 `docs/TASKS.md` 完成 P3.1，确保 `execute_research()` 只承担 payload 完整性和基础合法性检查，不把语义级约束冲突下沉到系统层

### [test] 补齐 P2.6 Session 生命周期的启动与退出覆盖
- 文件：`tests/test_app.py`、`tests/test_cli.py`、`docs/CHANGELOG.md`
- 变更：
  1. 新增启动阶段测试，覆盖“仅存在历史 session、无 active session 时，系统创建新 active session 且不回注历史内容”
  2. 新增 CLI 退出测试，直接断言 `/quit` 后 `current_session.json` 仍存在且关键字段内容完整保留
- 原因：按 `docs/TESTING.md` 收口 P2.6 对应的 Session lifecycle 测试，避免仅依赖较重的 smoke case 间接覆盖
- 后续：如果未来 CLI 增加“新开对话”命令，应继续补一条从 CLI 入口触发 `start_new_session` 的回归测试

### [implementation] 完成 P2.6 的显式新会话切换与历史保留
- 文件：`src/store/document_store.py`、`src/app.py`、`tests/test_document_store.py`、`tests/test_app.py`、`docs/CHANGELOG.md`
- 变更：
  1. 为 `DocumentStore` 新增 active session 切换能力，支持在覆盖 `current_session.json` 前把旧 active session 以 `{session_id}.json` 的形式保留为历史副本
  2. 为应用层新增显式新开会话入口，在启动阶段先执行恢复检查，再根据请求创建新的 active session
  3. 为新会话创建补充唯一 `session_id` 生成保护，避免与当前 active session 或已有历史文件冲突
  4. 补充 `P2.6` 定向测试，覆盖“保留旧 active session 为历史”“启动恢复后再新开会话”两条关键路径
- 原因：按 `TASKS.md` 收口 Session 生命周期管理中仍缺失的“显式开启新对话但保留旧 session”能力，同时保持启动恢复检查顺序符合架构文档
- 后续：CLI 或其他入口若需要支持“新开对话”命令，应直接复用应用层新增入口，不要在上层重复实现 session 文件切换逻辑

### [test] 补齐 P2.4/P2.5 的恢复分支与 onboarding 集成覆盖
- 文件：`tests/test_document_store_phase2.py`、`tests/test_app.py`、`docs/CHANGELOG.md`
- 变更：
  1. 为 `apply_pending_profile_updates()` 新增 `复购/换代` 可正常落长期画像的测试
  2. 为 `纯咨询` intent 新增跳过长期画像写入且清除草稿的测试
  3. 为应用层新增 onboarding 集成测试，覆盖“新用户标注 -> `onboard_user` 写入 demographics -> 下一轮不再触发 onboarding 并恢复常规对话”
  4. 新增“已有完整 demographics 的用户不出现 onboarding 标注”的应用层测试
- 原因：按 `docs/TESTING.md` 和 `TASKS.md` 补齐 P2.4 / P2.5 仍缺的测试分支与链路验证，在不修改生产代码的前提下增强回归保护
- 后续：若未来调整 onboarding 标注文案或恢复规则，应同步更新这些断言，继续保持测试与文档口径一致

### [implementation] 收紧 P2.4/P2.5 的 onboarding 持久化与画像草稿收口
- 文件：`src/router/action_router.py`、`tests/test_action_router.py`、`docs/CHANGELOG.md`
- 变更：
  1. 将 `onboard_user` 的 demographics 写入路径从 router 直接读写 `global_profile.json` 收口为统一调用 `DocumentStore.save_global_profile()`
  2. 为 `action_payload.demographics` 增加系统侧必填校验，要求 `gender`、`age_range`、`location` 必须存在且为非空字符串；非法 payload 改为写入 `error_state.validation_warnings` 并拒绝落盘
  3. onboarding 写入时保留已有 `global_profile` 的其他 section，并保留已有 `demographics` 中非 onboarding 字段
  4. 补充 `ActionRouter` 单测，覆盖 onboarding 成功写入、保留已有画像信息，以及缺字段/空字符串时不落盘的错误路径
- 原因：按 `TASKS.md` 完成 P2.4 / P2.5 的剩余收口，避免 router 绕过 store 层直接写文件，同时把 onboarding payload 约束收紧到文档定义
- 后续：如后面增加更细粒度 profile schema 校验，应继续保持通过 store 层统一落盘

## 2026-04-15

### [fix] 修正品类调研软提示触发语义并恢复静态检查通过
- 文件：`src/context/session_provider.py`、`tests/test_session_provider.py`、`tests/test_app.py`、`tests/test_action_router.py`、`tests/test_research_agent.py`、`src/agents/research_agent.py`、`docs/PROMPTS.md`、`docs/TESTING.md`、`docs/SPEC.md`、`docs/ARCHITECTURE.md`、`docs/CHANGELOG.md`
- 变更：
  1. 将品类调研软提示从“第 3 次调研完成后下一轮出现”修正为“已调研 2 个不同 category、准备进入第 3 个不同 category 前预先出现”
  2. 将 `SessionContextProvider` 的统计口径从调研事件总数改为不同 `category` 去重计数，避免同品类补充调研误触发提示
  3. 将相关 app / session provider 测试改为覆盖“第 3 个不同品类前预警”与重复 category 不重复计数
  4. 将测试中的 `ProductSearchOutput.search_meta` 构造改为显式 `SearchMeta`，并删除未使用导入，恢复 `ruff` / `mypy` 通过
- 原因：修复 review 发现的软提示时机偏晚、统计语义不准，以及 `search_meta` 强类型落地后测试未同步导致的静态检查回归

### [docs] 收紧 search_meta source of truth 定义
- 文件：`docs/INTERFACES.md`、`docs/SPEC.md`、`docs/TESTING.md`、`docs/CHANGELOG.md`
- 变更：
  1. 将 `INTERFACES.md` 中 `ProductSearchOutput.search_meta` 从宽松 `dict` 改为显式 `SearchMeta` 子模型
  2. 将 `search_meta` 的描述从“推荐字段”收紧为“固定核心字段”，与当前产品逻辑、实现和测试口径一致
  3. 在 SPEC / INTERFACES 中补齐 `search_failed` 作为 `error_state.events` 的正式事件示例
  4. 在 TESTING 中补充 `SearchMeta.result_status` 枚举约束的校验要求
- 原因：避免 source of truth 文档继续保留过宽定义，导致 prompt、测试或新调用点重新漂回自由结构

### [implementation] 同步 search_meta 契约与品类调研软提示注入
- 文件：`src/models/research.py`、`src/router/action_router.py`、`src/context/session_provider.py`、`tests/test_models.py`、`tests/test_action_router.py`、`tests/test_app.py`、`tests/test_research_agent.py`、`tests/test_document_store.py`、`tests/test_phase1_smoke.py`、`tests/test_session_provider.py`
- 变更：
  1. 为 `ProductSearchOutput` 增加结构化 `SearchMeta` 子模型，正式约束 `retry_count`、`result_status`、`search_expanded`、`expansion_notes`
  2. 在 `ActionRouter` 的产品搜索后处理中，将 `search_meta` 稳定映射到 `error_state.search_retries` 和结构化 `events`
  3. 在品类调研后处理里记录 `dispatch_category_research` 事件，供 `SessionContextProvider` 统计并在第 3 次及以上调研时注入系统软提示
  4. 同步更新模型、router、app、document store、smoke 与 session provider 测试，覆盖新的 `search_meta` 契约和软提示出现时机
- 原因：落实 2026-04-15 文档收口后的正式接口与系统侧提示行为，避免继续依赖 `notes` 文本猜测错误状态

### [docs] 修复多子问题任务的关键漏洞并补充品类通用性说明
- 文件：`docs/PROMPTS.md`、`docs/SPEC.md`、`docs/INTERFACES.md`
- 变更：
  1. **修复漏洞 1：全局约束缺失机制**
     - 在 `PROMPTS.md` 推荐阶段新增"多子问题任务的全局约束管理"章节
     - 明确要求在开始第一个子问题前识别全局约束（总预算、时间限制等）
     - 要求基于品类知识给出预算分配建议并记录到 `goal_summary`
     - 要求推荐时回顾全局约束，确保不破坏整体可行性
  2. **修复漏洞 2：焦点切换时的决策连续性缺失**
     - 在 `PROMPTS.md` 推荐阶段新增"焦点切换规则"章节
     - 要求切换前在 `user_message` 中总结当前子问题状态
     - 明确回看处理策略：优先从对话历史提取，必要时重新搜索
  3. **修复漏洞 3：品类调研次数软提示语义不清**
     - 在 `PROMPTS.md` 第零层新增"品类调研次数软限制"章节
     - 明确软提示内容和主 Agent 应对方式
     - 说明软提示不阻止调用，只要求在 `internal_reasoning` 中解释必要性
  4. **修复漏洞 4：推荐前 review 机制缺失**
     - 在 `PROMPTS.md` 推荐阶段新增"推荐前自检"章节
     - 要求每次输出推荐前检查：硬约束匹配、全局约束、候选质量
  5. **修复漏洞 5：`existing_items` 和 `missing_items` 使用时机不明确**
     - 在 `PROMPTS.md` 需求挖掘阶段新增"已有物品和缺失项的询问时机"章节
     - 明确何时询问、如何记录、如何使用
  6. **修复模糊地带 1：多子问题任务的完成判定**
     - 在 `PROMPTS.md` 会话收尾部分新增"多子问题任务的完成判定"章节
     - 区分"阶段性完成"和"整体完成"
     - 明确画像更新只在整体完成时触发
  7. **修复模糊地带 2：`goal_summary` 格式自由度**
     - 在 `PROMPTS.md` 需求挖掘阶段新增"goal_summary 的写入格式"章节
     - 提供推荐格式和多个跨品类示例
  8. **补充品类通用性说明**
     - 在 `PROMPTS.md` 身份定位部分新增"品类范围说明"
     - 在 `SPEC.md` §1.2 补充品类示例并新增 NOTE 说明系统不限制品类范围
     - 在 `SPEC.md` §1.4 扩充任务形态示例，涵盖多个品类
     - 在 `INTERFACES.md` 开头新增关于示例数据的说明
- 原因：
  - 通过系统性 review 发现多子问题任务存在 5 个关键漏洞和 2 个模糊地带
  - 文档中使用户外装备作为示例可能导致误解系统局限于该品类
- 后续：所有修复均为 prompt 层面的指导补充，不涉及 schema 或架构变更，可直接应用

### [docs] 收口多目标任务语义并补齐搜索运行契约
- 文件：`docs/SPEC.md`、`docs/PROMPTS.md`、`docs/INTERFACES.md`、`docs/ARCHITECTURE.md`、`docs/TESTING.md`、`docs/CHANGELOG.md`
- 变更：
  1. 将搭配/补齐/升级类任务的 V1 口径明确为“单焦点顺序推进”，保留 `goal_summary` 作为整体目标锚点，但将 `product_type` 和 `candidate_products` 明确为“当前焦点”语义，不再暗示并行候选池或跨焦点统一排序
  2. 将 `dispatch_category_research` 从“单 session 硬上限 2 次”改为“建议值 2 次 + 软提示”，避免与合法的多子问题流程冲突
  3. 为 `ProductSearchOutput` 新增结构化 `search_meta` 运行元信息，并在 SPEC / ARCHITECTURE / TESTING 中明确由应用层据此写入 `error_state.search_retries` 与相关 `events`
  4. 清理搜索策略残留旧口径，将“搜索关键词基于用户所在城市决定”统一改回 `research_brief` 主导的语义决策
- 原因：修复文档 review 中发现的范围-状态模型不一致、错误状态缺少结构化来源，以及搜索策略重构后仍有旧表述残留的问题
- 后续：代码实现与测试用例需要同步到新的 `search_meta` 契约和“单焦点顺序推进”口径

### [implementation] 完成搜索策略重构的代码实现
- 文件：`src/agents/research_agent.py`、`tests/test_research_agent.py`
- 变更：
  1. 删除 `SEARCH_INSTRUCTION_FOR_CHINA` 和 `SEARCH_INSTRUCTION_FOR_NON_CHINA` 常量
  2. 删除 `_is_china_location()` 和 `get_search_language_instruction()` 函数
  3. 删除 `_load_global_profile()` 函数（不再需要读取 location）
  4. 新增 `DEFAULT_RESEARCH_BRIEF` 常量作为默认搜索策略提示
  5. 修改 `build_product_search_instructions()` 和 `build_category_research_instructions()`：
     - 移除 `location` 参数
     - 从 `action_payload.research_brief` 获取搜索策略提示
     - 若未提供则使用 `DEFAULT_RESEARCH_BRIEF`
     - 将 `research_brief` 填充到模板的 `{research_brief}` 占位符
  6. 修改 `execute_research()`：移除 `global_profile` 和 `location` 读取逻辑，直接调用更新后的 `build_*_instructions()`
  7. 更新测试用例：
     - 删除 `test_search_language_instruction_switches_by_location` 测试
     - 更新 `test_build_product_search_instructions_renders_template` 和 `test_build_category_research_instructions_renders_template`，验证默认 `research_brief`
     - 新增 `test_build_product_search_instructions_uses_custom_research_brief` 和 `test_build_category_research_instructions_uses_custom_research_brief`，验证自定义 `research_brief`
     - 简化 `test_execute_research_creates_new_agent_each_call` 和 `test_execute_research_supports_category_research`，移除不再需要的 `global_profile.json` mock
- 原因：落地 2026-04-14 的搜索策略重构设计，将搜索语言决策从系统层硬编码移至主 Agent 语义判断
- 后续：所有测试通过，代码实现与文档规范完全一致

## 2026-04-14

### [refactor] 将搜索策略决策从系统层移至主 Agent
- 文件：`docs/PROMPTS.md`、`docs/INTERFACES.md`、`docs/SPEC.md`、`docs/ARCHITECTURE.md`
- 变更：
  1. 删除 `{search_language_instruction}` 占位符及其硬编码规则（根据 location 判断"搜中文/搜英文"）
  2. 新增 `research_brief` 字段（可选），由主 Agent 在 dispatch 时传递自然语言搜索策略提示
  3. 在主 Agent prompt 中增加"搜索策略决策"指导，要求主 Agent 根据 location、用户语言、品类特征等综合判断后填写 `research_brief`
  4. 研究 Agent 模板改为接收 `{research_brief}` 占位符，若未提供则使用默认提示
  5. 更新 ARCHITECTURE.md 的分工原则示例，明确"搜索语言策略"属于语义判断，应由主 Agent 做
  6. 更新 SPEC.md §6.4，将"搜索语言策略"改为"搜索策略决策"
- 原因：
  - 硬编码的 location → 搜索语言映射削弱了主 Agent 的决策空间，无法处理"用户在中国但询问国际品牌"等复杂场景
  - 自然语言 `research_brief` 比结构化 `search_strategy` 枚举更灵活，避免过早定死策略空间
  - 保持子 Agent 模板独立性，系统层只负责模板选择和变量填充，不做语义判断
- 后续：代码实现时需同步修改 `research_agent.py`（删除 `_is_china_location()` 等函数，修改 `build_*_instructions()` 和 `execute_research()`）

### [implementation] 完成 P2.2 品类调研执行与后处理
- 文件：`src/agents/prompts.py`、`src/agents/research_agent.py`、`src/router/action_router.py`、`tests/test_research_agent.py`、`tests/test_action_router.py`
- 变更：扩展研究 Agent 支持 `dispatch_category_research`，加入品类调研 payload 校验、模板渲染与 `CategoryResearchOutput` 结构化执行；在 Action Router 中接通品类调研后处理，支持首次创建 knowledge 文档与向已有文档增量合并新的 `product_types.*` section，并写入 `pending_research_result`。
- 原因：按 `TASKS.md` 落地 P2.2，为后续完整 KnowledgeContextProvider 和新品类/新品类目扩展提供真实的知识调研入口。

### [fix] 补齐 P1/P2 上下文注入与 router 容错行为
- 文件：`src/context/session_provider.py`、`src/context/knowledge_provider.py`、`src/context/profile_provider.py`、`src/app.py`、`src/router/action_router.py`、`src/store/document_store.py`
- 变更：为 SessionContextProvider 增加超过 7 天的 staleness 标注与 pending 搜索结果过期提醒；将 KnowledgeContextProvider 改为按 `category + product_type` 选择性加载，并在缺失品类/产品类型知识时注入系统标注与已有 product_type 列表；新增 ProfileContextProvider 并接入默认应用上下文；ActionRouter 对非法 `next_action` 和非法 dispatch/onboarding payload 改为写入 `error_state.validation_warnings` 后返回，不再直接崩溃；同时允许首次写入 session 时保留显式 `last_updated`，以支持 staleness 测试初始化场景。
- 原因：修复新补测试暴露出的上下文缺口与 router 容错不符合 `TESTING.md` 的问题，且不提前展开其他阶段功能。

### [fix] 修正 profile 恢复检查的原子性与 initialize_session 返回一致性
- 文件：`src/store/document_store.py`、`src/app.py`、`tests/test_document_store_phase2.py`、`tests/test_app.py`
- 变更：将 `apply_pending_profile_updates()` 改为先完整校验再提交，并在恢复失败时保持长期画像与 session 草稿原状，避免部分写入；`initialize_session()` 在执行恢复检查后重新加载 `current_session.json` 再返回，确保调用方拿到的是初始化后的最新 session。
- 原因：修复恢复检查中的状态不一致风险，确保启动阶段接口语义与实际持久化状态一致。

### [fix] 实现 pending_profile_updates 的启动恢复写入逻辑
- 文件：`src/store/document_store.py`、`tests/test_document_store_phase2.py`
- 变更：将 `apply_pending_profile_updates()` 从 stub 扩展为真实恢复检查逻辑；在 intent 为 `自用选购`/`复购/换代`、推荐轮次为 `"完成"` 且 error_state 无明显异常时，正式写入 `global_profile.json` 和 `category_preferences/{category}.json`，随后清除 session 中的草稿；对 `送礼`、`纯咨询` 或异常状态则跳过并清除草稿。
- 原因：修复之前遗留的 Phase 1 stub，避免阻塞 P2.4/P2.6 的恢复检查与长期画像写入。

### [implementation] 完成 P2.1 DocumentStore 扩展
- 文件：`src/store/document_store.py`、`tests/test_document_store_phase2.py`
- 变更：在现有 session CRUD 基础上新增 knowledge/profile 的完整读写接口，支持知识文档选择性加载、product_type 增量合并，以及 global profile/category preferences 的 section 级替换更新；补充对应单元测试。
- 原因：按 `TASKS.md` 落地 P2.1，为后续品类调研后处理、完整 ContextProviders 和 profile 持久化提供基础存储接口。

### [implementation] 完成 P1.10 端到端冒烟测试
- 文件：`tests/test_phase1_smoke.py`、`docs/SMOKE_TEST_RECORD.md`
- 变更：新增基于 CLI 的 Phase 1 端到端冒烟测试，使用真实 `run_cli()`、应用调度层、Action Router 和 DocumentStore，结合固定主 Agent/研究结果替身跑通冲锋衣场景的多轮闭环；补充本次执行记录。
- 原因：按 `TASKS.md` 落地 P1.10，验证当前 Phase 1 主路径在不依赖外部 API 凭证时也能完成最小闭环和关键状态写入。

### [fix] 修正 dispatch 消息时机、恢复检查时机与画像草稿契约
- 文件：`src/router/action_router.py`、`src/app.py`、`src/cli.py`、`tests/test_action_router.py`、`tests/test_app.py`、`tests/test_cli.py`
- 变更：为 `dispatch_product_search` 增加消息发射回调，确保过渡消息在研究执行前就发送给用户；将恢复检查从每轮 `run_turn()` 移到显式启动阶段 `initialize_session()`；当 `recommendation_round` 首次变为 `"完成"` 但缺少 `profile_updates` 时改为抛出显式错误而不是静默丢弃。
- 原因：修正与 `ARCHITECTURE.md` / `INTERFACES.md` 不一致的行为，避免搜索前静默、重复恢复检查和画像草稿丢失。

### [implementation] 完成 P1.7-P1.9 上下文、CLI 与知识 fixture
- 文件：`src/context/session_provider.py`、`src/context/knowledge_provider.py`、`src/cli.py`、`tests/fixtures/户外装备.json`、`tests/test_session_provider.py`、`tests/test_knowledge_provider.py`、`tests/test_cli.py`
- 变更：实现 Phase 1 的 `SessionContextProvider` 与最小 `KnowledgeContextProvider`，并接入 `app.py` 的默认 context 构建；新增 CLI 异步入口，支持欢迎语、循环输入、启动恢复检查、`/quit`/`/end` 退出和 `Ctrl+C` 优雅退出；新增户外装备知识 fixture 供 Phase 1 直接加载。
- 原因：按 `TASKS.md` 完成 P1.7-P1.9，使当前系统具备正式的 session 注入格式、可运行 CLI，以及跳过品类调研的测试知识文档。
- 后续：P2.3 再补完整的 Profile/Knowledge ContextProvider 规则与 staleness 注入逻辑。

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
