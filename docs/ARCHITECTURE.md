# ARCHITECTURE.md — 系统架构与运行模型

> 本文档定义购物推荐 Agent 的系统架构、组件关系、运行模型和关键工程决策。阅读本文档前建议先熟悉 SPEC.md 中的产品规格。

---

## 一、技术栈

| 层级 | 技术选型 |
|------|---------|
| 语言 | Python |
| Agent 框架 | Microsoft Agent Framework (MAF) |
| LLM 接口 | MAF 内置多模型支持（OpenAI / Anthropic / Google） |
| 结构化输出 | Pydantic（MAF 原生集成 `output_type`） |
| 数据持久化 | 本地 JSON 文件（`data/` 目录） |
| 搜索能力 | 模型内置 web search（推荐）或 Tavily / SerpAPI 包装 |
| 用户界面 | CLI（V1） |

---

## 二、架构总览

### 2.1 组件关系图

```
┌──────────────────────────────────────────────────────────────────────┐
│                    应用调度层 (Application Layer)                      │
│                                                                      │
│  职责：                                                               │
│  • 管理外部循环（多轮会话的 Observe → Reason → Act）                   │
│  • 路由 next_action（ask_user / dispatch / recommend / onboard_user） │
│  • 管理研究 Agent 生命周期（创建→运行→销毁→后处理）                     │
│  • 执行文件写入（session / knowledge / profile）                       │
│  • 边界保护（最大轮数、最大 dispatch 次数）                             │
│  • 日志记录                                                          │
│                                                                      │
│  入口：CLI (V1)                                                       │
│                                                                      │
│  ┌──────────────────┐       ┌──────────────────────┐                 │
│  │  ContextProviders │       │    DocumentStore      │                 │
│  │                  │───────│                      │                 │
│  │  每轮从文件加载   │  读取  │  本地 JSON 文件 CRUD  │                 │
│  │  知识/画像/session│───────│  data/ 目录           │                 │
│  │  注入主Agent的    │       │                      │                 │
│  │  context         │       │  知识/画像/session    │                 │
│  └───────┬──────────┘       └──────────┬───────────┘                 │
│          │ 注入 context                 │ 写入文件                     │
│          ▼                              ▲                             │
│  ┌───────────────────────────────────────────────────────────┐       │
│  │                  主 Agent（纯推理器）                       │       │
│  │                                                           │       │
│  │  • 无 FunctionTool                                        │       │
│  │  • 输入：context（文档+用户消息）                           │       │
│  │  • 输出：DecisionOutput（Pydantic 结构化）                  │       │
│  │  • 每次调用 = 一次 LLM 推理，无内部工具调用循环              │       │
│  │  • instructions：策略规则全集                               │       │
│  │  • model：GPT-4o / Claude Opus                            │       │
│  │                                                           │       │
│  └───────────────────────────────────────────────────────────┘       │
│          │ 输出 DecisionOutput                                       │
│          ▼                                                           │
│  ┌───────────────────────────────────────────────────────────┐       │
│  │              Action Router（应用层代码）                    │       │
│  │                                                           │       │
│  │  读取 next_action → 执行对应系统动作：                      │       │
│  │  • ask_user/recommend → 返回 user_message 给用户           │       │
│  │  • dispatch_*        → 创建研究 Agent（见下方）            │       │
│  │  • onboard_user      → 写入 demographics + 返回消息        │       │
│  │                                                           │       │
│  │  同时：                                                    │       │
│  │  • 应用 session_updates → DocumentStore 写入 session 文件 ──┘       │
│  └───────────┬───────────────────────────────────────────────┘       │
│              │ dispatch_* 时创建                                      │
│              ▼                                                       │
│  ┌───────────────────────────────────────────────────────────┐       │
│  │            研究 Sub-Agent（有工具，MAF管理内部循环）         │       │
│  │                                                           │       │
│  │  • tools：web_search（内置或 Tavily API 包装）             │       │
│  │  • 每次调用新建实例，完成后销毁（独立 context）             │       │
│  │  • MAF 管理内部工具调用循环：                               │       │
│  │    LLM→搜索→结果→再推理→再搜索→...→ResearchOutput          │       │
│  │  • model：GPT-4o-mini / Gemini Flash                     │       │
│  │  • 输出：ResearchOutput（Pydantic 结构化）                  │       │
│  │                                                           │       │
│  └───────────────────────────────────────────────────────────┘       │
│              │ 返回 ResearchOutput                                    │
│              ▼                                                       │
│  ┌───────────────────────────────────────────────────────────┐       │
│  │              Dispatch 后处理（应用层代码）                   │       │
│  │                                                           │       │
│  │  • 结构校验（Pydantic validator）                          │       │
│  │  • 品类调研结果 → 写入 knowledge 文件                      │       │
│  │  • 产品搜索结果 → 写入 session pending_research_result     │       │
│  │  • 同时刷新 session candidate_products                    │       │
│  │  • 回到外部循环步骤 1（再次调用主 Agent）                   │       │
│  └───────────────────────────────────────────────────────────┘       │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────────┐
│                       外部服务层                                      │
│                                                                      │
│  • LLM Providers — OpenAI / Anthropic / Google API                   │
│  • Web Search    — 模型内置搜索 或 Tavily / SerpAPI                   │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 框架角色分工

| MAF 承担的 | 项目自建的 |
|-----------|-----------|
| 研究 Agent 的 agent loop（LLM ↔ 搜索工具循环） | 外部循环（应用调度层的多轮会话管理） |
| 多模型支持（不同 Agent 用不同模型） | DocumentStore（三层文档架构 CRUD） |
| 结构化输出（Pydantic → JSON schema → 模型约束） | ContextProvider 逻辑（选择性加载） |
| 研究 Agent 的工具调用循环管理（开发者提供工具函数，MAF 管理调用机制） | 所有业务逻辑（urgency、推荐策略、JTBD 等） |
| Agent 实例管理（创建、运行、销毁） | Action Router（next_action 路由） |

**核心判断**：MAF 在这个项目中的角色是**研究 Agent 的运行时**（管理搜索工具调用循环）和**结构化输出的保障**（Pydantic 集成）。项目的大部分架构——外部循环、状态管理、文档体系、业务策略——由应用层和 System Prompt 承载。

---

## 三、两层循环运行模型

本项目的运行时包含两个层级不同的循环。理解这两层循环是理解整个系统的核心。

### 3.1 外部循环（应用调度层管理）— 多轮会话循环

> [!NOTE]
> 以下为伪代码，展示逻辑流程。实际实现中 `execute_research` 是 async 函数（MAF 的 `agent.run()` 是异步的），外部循环用 `asyncio.run()` 或 `await` 调用。

```python
session = load_or_create_active_session()
run_recovery_check_if_needed(session)   # 处理 staleness + pending_profile_updates

while session.is_active:
    # 1. Observe — ContextProviders 加载最新状态
    context = load_context(session, knowledge, profile)

    # 2. Reason — 调用主 Agent（一次 LLM 推理）
    decision: DecisionOutput = main_agent.run(context + user_input)

    # 3. Act — 写入 session_updates + 路由 next_action
    if decision.session_updates:
        write_session_updates(decision.session_updates)

    match decision.next_action:
        case "ask_user" | "recommend":
            send_to_user(decision.user_message)
            user_input = wait_for_user()           # 等待用户输入

        case "dispatch_category_research":
            send_to_user(decision.user_message)     # 先发消息给用户（如"我先了解一下..."）
            result = execute_research(               # 创建研究 Agent
                task_type="dispatch_category_research",
                action_payload=decision.action_payload
            )
            write_knowledge(result)                 # 写入 knowledge 文件
            save_pending_research_result(result)    # 放入 session
            user_input = None                       # 不等用户；走完统一后置检查后回到步骤 1

        case "dispatch_product_search":
            send_to_user(decision.user_message)     # 先发消息给用户（如"好的，我来搜索..."）
            result = execute_research(
                task_type="dispatch_product_search",
                action_payload=decision.action_payload
            )
            save_pending_research_result(result)
            refresh_candidate_products(result)      # 保存研究 Agent 初筛候选池
            reset_recommendation_round()            # 自动重置为 "未开始"
            user_input = None                       # 不等用户；走完统一后置检查后回到步骤 1

        case "onboard_user":
            write_demographics(decision.action_payload)
            send_to_user(decision.user_message)
            user_input = wait_for_user()

    # 4. 后置检查
    if pending_research_result_was_consumed_this_turn():
        clear_pending_research_result()

    if recommendation_round_became("完成"):
        save_pending_profile_updates(decision.profile_updates)

    # 5. 边界检查
    check_max_turns()
    check_max_dispatches()

    if decision.next_action in {"dispatch_category_research", "dispatch_product_search"}:
        continue
```

**关键设计点**：
- **dispatch 时也发 user_message**：dispatch action 的 DecisionOutput 通常包含给用户的过渡消息（如"好的！我先了解一下冲锋衣…"），在启动研究 Agent 之前就发给用户，避免长时间无响应
- `dispatch_*` 路由不等用户输入，但会先执行统一的后置检查和边界检查，再回到循环顶部——研究 Agent 的结果通过 `pending_research_result` 放入 session，下一轮 ContextProvider 自动注入，主 Agent 在下一轮推理中消费
- **语义级约束冲突检查由主 Agent 在 dispatch 前完成**；`execute_research()` 仅做 payload 完整性和基础合法性的 sanity check
- `recommend` 和 `ask_user` 是两个不同的 action，但系统层行为相同（都返回 user_message 给用户并等待输入），保留两个值是为了语义清晰和日志分析
- `pending_research_result` 是一次性交接字段；`candidate_products` 是推荐周期内可持续复用的候选池，供两轮推荐共享
- 对搭配/补齐/升级类任务，V1 采用**单焦点顺序推进**：`goal_summary` 保留整体目标，`product_type` 表示当前焦点，`candidate_products` 只保存当前焦点的一批候选，不承担多子问题并行候选池职责
- 后置检查在每轮 action 路由之后执行，确保 `pending_research_result` 清理和 `recommendation_round = "完成"` 的草稿落盘不会被遗漏
- `run_recovery_check_if_needed()` 是应用层确定性逻辑：若当前活跃 session 带有未应用的 `pending_profile_updates`，系统在下一次启动时先完成恢复检查，再决定是否写入长期画像

### 3.2 内部循环（MAF 框架管理）— 仅研究 Agent 内部

```
研究 Agent 被调用后，MAF 管理其工具调用循环：
LLM推理 → 调用搜索工具 → 获取结果 → 再推理 → 再搜索 → ... → 最终输出 ResearchOutput
```

MAF 自动管理工具调用循环的启动和终止。应用层只需要创建 Agent 实例、传入 instructions 和任务描述、接收最终的 ResearchOutput。

**主 Agent 没有内部循环**——每次被调用时，它接收 context，做一次完整推理，输出一个 DecisionOutput。所有信息已通过 ContextProvider 预加载，不需要中途调工具获取信息。

### 3.3 为什么 ReAct 仍然成立

ReAct 的 Observe → Reason → Act 发生在外部循环的每一轮：

| 步骤 | 实现 |
|------|------|
| **Observe** | ContextProvider 注入最新的 session state、知识文档、画像 |
| **Reason** | 主 Agent 分析用户输入 + 当前状态，更新理解，判断 urgency，决定下一步 |
| **Act** | 应用层根据 `next_action` 执行系统动作 |

---

## 四、Agent 通信模型

### 4.1 通信拓扑

主 Agent 和研究 Agent 之间**没有直接通信**。应用调度层是唯一的中间人：

```
主 Agent ──(DecisionOutput)──→ 应用调度层 ──(创建+调用)──→ 研究 Agent
                                    ↑                           │
                                    │                           │
                                    └──(注入下轮context)←──(ResearchOutput)
```

### 4.2 通信介质

| 通信方向 | 介质 | 内容 |
|---------|------|------|
| 主 Agent → 应用层 | DecisionOutput 的 `next_action` + `action_payload` | "请执行品类调研/产品搜索，搜索条件是..." |
| 应用层 → 研究 Agent | 创建 Agent 实例时传入的 instructions + 任务描述 | 来自 `src/prompts/` 的品类调研模板或产品搜索模板，已填充搜索条件和搜索语言指引 |
| 研究 Agent → 应用层 | ResearchOutput（Pydantic 结构化输出） | 品类知识或产品列表 |
| 应用层 → 主 Agent | 通过 ContextProvider 注入下一轮 context | 研究结果（pending_research_result）、活动候选池（candidate_products）、更新后的 session state |

### 4.3 用冲锋衣示例走一遍架构

以 SPEC.md §14.2 场景 A 的前两轮为例：

```
用户: "想买一件冲锋衣"

━━━ 外部循环 第1轮 ━━━

[Observe] ContextProviders 加载：
  • sessions/current_session.json → 空（新会话）
  • user_profile/global_profile.json → 已有 demographics
  • knowledge/户外装备.json → 不存在
  注入 context 中包含标注："当前品类无知识文档"

[Reason] 调用主 Agent（一次 LLM 推理）：
  输入：context + "想买一件冲锋衣"
  推理：品类=户外装备，产品类型=冲锋衣，知识文档不存在 → 需要先调研
  输出：DecisionOutput {
    user_message: "好的！我先了解一下冲锋衣这个品类...",
    next_action: "dispatch_category_research",
    action_payload: {
      category: "户外装备",
      product_type: "冲锋衣",
      user_context: "用户只表达了想买冲锋衣，具体场景和预算尚未明确"
    },
    session_updates: { decision_progress: { stage: "品类认知构建", ... } }
  }

[Act] 应用层执行：
  1. 写入 session_updates → sessions/current_session.json
  2. 将 user_message 发给用户
  3. 创建研究 Agent → 执行品类调研（MAF 管理内部搜索循环）
  4. 研究 Agent 返回 CategoryResearchOutput（品类知识）
  5. 后处理：写入 knowledge/户外装备.json
  6. 将研究结果放入 session（pending_research_result）
  7. 不等用户输入 → 回到循环顶部

━━━ 外部循环 第2轮（系统自动触发，非用户输入）━━━

[Observe] ContextProviders 加载：
  • session state（已更新，含 pending_research_result）
  • knowledge/户外装备.json（刚写入的品类知识）
  • global_profile

[Reason] 调用主 Agent：
  输入：context（含品类知识）+ 原始用户消息
  推理：已有冲锋衣知识，所有维度 urgency=16（都是未知），需要批量提问
  输出：DecisionOutput {
    user_message: "先了解几个关键信息：1.什么场景穿？2.预算？3.品牌偏好？",
    next_action: "ask_user",
    session_updates: { requirement_profile: { /* 初始化维度 */ } }
  }

[Act] 应用层执行：
  1. 写入 session_updates
  2. 清除 pending_research_result
  3. 将 user_message 发给用户
  4. 等待用户输入
```

---

## 五、工具策略

### 5.1 主 Agent：无 FunctionTool

主 Agent 是**纯推理器**：接收 context + 用户消息 → 输出 DecisionOutput。

它不需要在推理过程中调用工具，原因：
1. 所有文档信息已通过 ContextProvider 预加载到 context 中
2. 所有系统动作（dispatch、文件写入、返回用户消息等）由应用层根据 `next_action` 执行
3. 不存在"需要中途获取外部信息再继续推理"的场景

### 5.2 研究 Agent：搜索工具

研究 Agent 需要在推理过程中主动搜索互联网，因此需要工具。有两种实现方式：

**方式一：使用模型内置 web search（推荐，如果可用）**

现代 LLM 很多自带 web search 能力。例如使用 OpenAI 的 GPT-4o-mini 时，可以直接开启内置 web search tool：
- 模型自主决定何时搜索、搜索什么关键词
- API 底层自动执行搜索引擎查询、抓取网页内容、返回给模型
- **不需要 `fetch_page`**——搜索+读取网页在底层是一体化的
- 不需要写任何自定义工具代码

**方式二：包装第三方搜索 API**

如果研究 Agent 使用不带内置搜索的模型（如 Claude），或需要更多控制：

```python
from tavily import TavilyClient

def search_web(query: str, max_results: int = 10) -> str:
    """搜索互联网获取相关信息。Tavily 会自动返回网页完整内容摘要。"""
    client = TavilyClient(api_key="...")
    response = client.search(query, max_results=max_results, include_raw_content=True)
    return response

# 创建研究 Agent 时传入
research_agent = Agent(
    tools=[search_web],  # MAF 自动将 Python 函数包装为 LLM 可调用的 tool
    ...
)
```

> [!NOTE]
> **FunctionTool 的含义**：就是写一个普通的 Python 函数（如上面的 `search_web`），传给 MAF Agent 的 `tools` 参数。MAF 自动从函数签名、类型注解和 docstring 中提取信息，生成 LLM 可理解的工具描述。LLM 在推理时决定要调用这个函数时，MAF 自动执行它并把结果返回给 LLM。

> [!NOTE]
> **Tavily 这类 AI 搜索 API 的特点**：不仅返回搜索结果标题和 URL，还会自动抓取并返回网页的完整内容摘要。所以使用 Tavily 时只需要一个 `search_web` 工具，不需要单独的 `fetch_page`——搜索和内容读取是一步完成的。

---

## 六、状态管理架构

### 6.1 数据目录结构

```
data/
├── sessions/
│   ├── current_session.json          # 当前活跃会话
│   └── {session_id}.json             # 可选历史保留文件（如 2026-04-10-143052.json）
├── knowledge/
│   └── {category}.json               # 品类知识（如 户外装备.json）
└── user_profile/
    ├── global_profile.json            # 宏观画像
    └── category_preferences/
        └── {category}.json            # 品类偏好（如 户外装备.json）
```

### 6.2 文件操作模型

**核心原则**：Agent 不直接操作文件。文件操作由应用调度层统一执行。

```
┌──────────────────────────────────────────────────────┐
│                   文件操作流程                         │
│                                                      │
│  [读取]  ContextProvider 从文件加载数据                │
│              ↓ 注入 context                          │
│  [推理]  Agent 看到完整的当前数据 + 用户新输入         │
│              ↓ 结合新信息，推理出应该怎么改            │
│  [声明]  Agent 在 DecisionOutput 中声明修改意图       │
│          (session_updates / action_payload)           │
│              ↓                                       │
│  [写入]  应用层读取声明，执行机械性的 JSON 读写        │
│                                                      │
└──────────────────────────────────────────────────────┘
```

**为什么 Agent 不直接操作文件**：
1. Agent 已经通过 ContextProvider 看到了文件内容——不需要"再读一次"
2. Agent 做的是语义推理（"把 priority 改成 4"），不需要做 `open()`/`write()` 等文件 I/O
3. 应用层统一管理文件操作更可控——便于日志、校验、回滚

### 6.3 各类文件的写入规则

| 文件 | 写入时机 | 写入方式 | 触发条件 |
|------|---------|---------|---------|
| `sessions/current_session.json` | 每轮 | section 级替换 + 系统管理临时字段 | DecisionOutput 包含 session_updates；dispatch 后处理会刷新 `pending_research_result` / `candidate_products`；推荐完成时写入 `pending_profile_updates` |
| `knowledge/*.json` | 品类调研完成后 | 新建或增量合并 product_type section | dispatch_category_research 后处理 |
| `user_profile/global_profile.json` | 下次启动恢复检查 / onboarding | section 级替换 | 系统检查 `pending_profile_updates` 并通过恢复规则后写入；onboard_user 时写入 demographics |
| `user_profile/category_preferences/*.json` | 下次启动恢复检查 | section 级替换 | 系统检查 `pending_profile_updates` 并通过恢复规则后写入 |

### 6.4 `session_updates` 写入机制

Agent 在 context 中已经看到完整的 session state。当它需要更新某些部分时，输出更新后的**整个 section**：

```python
# Agent 输出示例
session_updates = {
    "requirement_profile": {
        "dimension_weights": [
            {"dimension": "防水", "priority": 4, "confidence": 1, "urgency": 4, ...},
            {"dimension": "透气", "priority": 3, "confidence": 3, "urgency": 9, ...},
            # ... 所有维度，包括没变的
        ]
    },
    "decision_progress": {
        "stage": "需求挖掘",
        "current_blocker": "使用场景的'高海拔'未锚定",
        ...
    }
}

# 应用层执行（简单 key 覆盖）
current_session = DocumentStore.load_session()
for key, value in session_updates.items():
    current_session[key] = value
DocumentStore.save_session(current_session)
```

- 不需要 JSON Patch、不需要 diff 算法——Agent 负责推理出完整的更新后 section，应用层只做机械替换
- 合法的顶层 key 采用**白名单机制**，该机制作用于 `DecisionOutput.session_updates`，不作用于已经合并完成的完整 session state
- `pending_research_result` 由系统在主 Agent 完成下一轮消费后统一清除，不依赖 `session_updates`
- `candidate_products` 由系统在 `dispatch_product_search` 后处理时刷新，供两轮推荐复用
- `pending_profile_updates` 由系统在 `recommendation_round = "完成"` 时写入，不通过 `session_updates` 由 LLM 直接修改

### 6.5 Session 生命周期管理

#### Staleness 检测

在 session state 中通过 `last_updated` 时间戳进行 staleness 检查：

```python
# 应用层在加载 session 时
session = DocumentStore.load_session()
if session:
    days_since = (now - session["last_updated"]).days
    if days_since > 7:
        # 在 context 中标注 staleness
        session["_staleness_note"] = f"会话已暂停 {days_since} 天"
        if "pending_research_result" in session:
            session["_staleness_note"] += "。产品搜索结果可能已过期（价格/库存可能变化）"
```

**主 Agent 如何处理 staleness**：Agent 在 context 中看到 staleness 标注后自行判断：
- 用户偏好和需求画像仍有效 → 从上次中断的阶段继续
- 产品搜索结果可能过期 → 提示用户并重新 dispatch 产品搜索
- Instructions 中包含恢复策略："如果看到 staleness 标注，先向用户确认需求是否仍然一致"

#### 活跃 session 保留与恢复

`current_session.json` 是当前活跃会话的运行锚点，**默认长期保留，不因推荐周期完成而自动清空或归档**。系统在下次启动时先读取该文件，再决定：

| 场景 | 实现方式 |
|------|---------|
| 推荐周期刚完成 | `recommendation_round = "完成"` 时仅保存 `pending_profile_updates`，保留当前 session 供后续恢复检查 |
| 用户显式继续上次对话 | 直接复用当前 session，主 Agent 基于现有状态继续推进 |
| 用户开启新对话 | 系统可在保留旧 session 的前提下创建新的活跃 session，历史 session 不默认注入 context |
| 程序正常退出后再次启动 | 先对 current_session 执行恢复检查，再决定继续当前 session 还是新开会话 |

恢复策略依然是**系统层确定性行为**：LLM 不决定 session 是否保留，也不决定长期画像何时落库；这些都由应用层在启动时检查 `pending_profile_updates`、`error_state` 和 staleness 后统一处理。

#### 恢复所需信息

| 恢复所需信息 | 由哪个文档覆盖 |
|------------|---------------|
| 从哪个阶段继续 | session state `decision_progress.stage` |
| 已挖掘的需求 | session state `requirement_profile` |
| 用户偏好 | `global_profile` + `category_preferences` |
| 品类知识 | `knowledge/*.json`（不过期） |
| 产品数据是否过期 | session state `last_updated` 时间戳 |
| 是否有待应用画像草稿 | session state `pending_profile_updates` |

---

## 七、ContextProvider 设计

每轮对话前，ContextProviders 按以下顺序注入 context：

### 7.1 SessionContextProvider

```
→ 读取 sessions/current_session.json
→ 启动阶段已完成恢复检查；常规每轮不在 ContextProvider 中重复执行
→ 注入 decision_progress + requirement_profile + jtbd_signals + error_state + goal_summary/existing_items/missing_items（如有） + candidate_products（如有）
→ 如有 pending_research_result → 注入研究结果
→ 历史 session 默认不加载，除非进入显式恢复/审计流程
```

### 7.2 KnowledgeContextProvider

```
→ 从 session 中读取当前 category + product_type
→ 选择性加载 knowledge/{category}.json 中的：
  • category_knowledge（始终加载）
  • product_types.{current_type}（如果存在）
→ 如果文件不存在 → 注入标注 "需要品类调研"
→ 如果文件存在但缺 product_type section → 注入标注 "需要产品类型调研"
→ 同时注入该文件中已有的所有 product_type 名称列表（辅助品类归一化）
```

> [!IMPORTANT]
> ContextProvider 确保文档加载是**确定性的系统行为**，而非 LLM 自主决策。SPEC.md §5.2 中的选择性加载要求在此处实现。

### 7.3 ProfileContextProvider

```
→ 加载 user_profile/global_profile.json
  → 如果文件不存在，或 demographics 的 gender/age_range/location 任一缺失 → 注入标注 "新用户，请先执行轻量 onboarding（性别、年龄段、城市）"
→ 加载 user_profile/category_preferences/{category}.json（如果存在）
```

---

## 八、研究 Agent 独立 context 实现

每次 dispatch 创建新实例 = 新 context = 天然隔离：

```python
async def execute_research(task_type: str, action_payload: dict) -> ResearchOutput:
    """应用调度层内部，在处理 dispatch action 时调用"""

    # 0. payload sanity check（字段完整性 / 基础合法性）
    validate_dispatch_payload(action_payload)

    # 1. 选择 prompt 模板 + 填充变量（包括 research_brief）
    research_brief = action_payload.get("research_brief", "")
    if not research_brief:
        research_brief = "请根据任务目标，自主选择合适的搜索语言和关键词策略。"
    
    if task_type == "dispatch_category_research":
        instructions = CATEGORY_RESEARCH_TEMPLATE.format(
            category=action_payload["category"],
            product_type=action_payload["product_type"],
            user_context=action_payload["user_context"],
            research_brief=research_brief,
        )
        output_model = CategoryResearchOutput
    else:
        instructions = PRODUCT_SEARCH_TEMPLATE.format(
            product_type=action_payload["product_type"],
            search_goal=action_payload["search_goal"],
            budget=action_payload["constraints"].get("budget", "null"),
            gender=action_payload["constraints"].get("gender", "未提供"),
            key_requirements=action_payload["constraints"]["key_requirements"],
            scenario=action_payload["constraints"].get("scenario", "未提供"),
            exclusions=action_payload["constraints"].get("exclusions", []),
            research_brief=research_brief,
        )
        output_model = ProductSearchOutput

    # 2. 创建研究 Agent 实例（新 context）
    research_agent = Agent(
        name="research_agent",
        instructions=instructions,
        model="gpt-4o-mini",
        tools=[search_web],          # 或使用模型内置搜索
        output_type=output_model,
    )

    # 3. 运行（MAF 管理内部搜索循环）
    result = await research_agent.run(task_prompt)

    # 4. Agent 实例回收，context 销毁
    return result
```

**Pydantic `output_type` 的作用**：MAF 自动从 Pydantic 模型提取 JSON schema 传给 LLM 的 structured output 模式。研究 Agent 的输出被约束为指定的结构——不需要额外的 `extract_product_info` 工具，结构化提取由 LLM 原生完成。

---

## 九、Dispatch 后处理流程

研究 Agent 返回 ResearchOutput 后，应用层执行后处理：

### 9.1 品类调研后处理

```
dispatch_category_research 完成后:
  1. Pydantic 结构校验（CategoryResearchOutput）
  2. 检查 knowledge/{category}.json 是否存在
     → 不存在 → 新建文件，写入 category_knowledge + product_types.{type}
     → 存在 → 增量合并，仅添加新的 product_types.{type} section
  3. 将结果包装为 pending_research_result:
     { "type": "category_research", "result": {...} }
  4. 写入 session
  5. 回到外部循环步骤 1（系统自动触发下一轮推理）
```

### 9.2 产品搜索后处理

```
dispatch_product_search 完成后:
  1. Pydantic 结构校验（ProductSearchOutput）
  2. 将结果包装为 pending_research_result:
     { "type": "product_search", "result": {...} }
  3. 将 ProductSearchOutput 刷新为 candidate_products（当前推荐周期候选池，仅对应当前研究焦点）
  4. 写入 session
  5. 自动重置 recommendation_round = "未开始"
  6. 回到外部循环步骤 1（系统自动触发下一轮推理）
```

> [!IMPORTANT]
> 品类调研结果需要**同时做两件事**：(1) 写入 knowledge 文件持久化 (2) 放入 pending_research_result 供主 Agent 下一轮读取。产品搜索结果则同时进入两层临时存储：`pending_research_result` 用于下一轮的一次性交接，`candidate_products` 用于当前焦点下两轮推荐期间的候选池复用。

---

## 十、Action Router 契约

应用层根据 DecisionOutput 的 `next_action` 路由到对应的处理流程。Action Router 是**被动执行者**——它不判断 LLM 的 action 选择是否合理（那是 LLM 的认知决策），只验证 payload 格式并执行对应的系统动作。

| next_action | payload 要求 | 系统行为 | 后置动作 |
|-------------|-------------|---------|----------|
| `ask_user` | 无 | 发送 `user_message` 给用户 | 等待用户输入 |
| `recommend` | 无 | 发送 `user_message` 给用户 | 等待用户输入 |
| `dispatch_category_research` | `action_payload` 包含 category + product_type + user_context | 发送 `user_message` → `execute_research()` → 后处理（§9.1） | 不等用户输入，回到循环顶部 |
| `dispatch_product_search` | `action_payload` 包含 product_type + search_goal + constraints（其中 `budget` 可为 `null` / `unspecified`） | 发送 `user_message` → `execute_research()`（仅做 payload sanity check）→ 后处理（§9.2） | 不等用户输入，回到循环顶部 |
| `onboard_user` | `action_payload` 包含 demographics | 将 demographics 写入 `global_profile.json` + 发送 `user_message` | 等待用户输入 |

> [!NOTE]
> "何时应该输出 `dispatch_category_research`" 这类**触发时机判断**由 LLM 在 instructions 指引下自主完成（如"品类知识文档不存在时"），不是 Action Router 的职责。Action Router 只关注 payload 格式是否合法和执行正确的系统动作。

**每轮的通用后置动作**（在 action 路由之后执行）：
1. 如本轮消费了 `pending_research_result` → 清除该一次性交接字段
2. 检查 `recommendation_round` 是否变为 `"完成"` → 将 `profile_updates` 写为 `pending_profile_updates`
3. 边界检查（最大轮数、最大 dispatch 次数）

---

## 十一、数据格式策略

### 11.1 Pydantic vs Plain JSON 策略

| 数据类型 | 格式 | 理由 |
|---------|------|------|
| Agent 输出（`DecisionOutput`、`CategoryResearchOutput`、`ProductSearchOutput`） | **Pydantic 模型** | MAF 原生集成 `output_type`；应用层代码需要类型安全的字段访问；校验自动执行 |
| 持久化数据（session state / knowledge / profile） | **Plain JSON dict** | Schema 在 INTERFACES.md 中定义为文档约定；应用层只做机械读写；避免维护两份定义 |

**边界线**：Pydantic 只覆盖 "LLM → 应用层" 的接口，不覆盖数据文档。

> 所有 Pydantic 模型定义和 JSON Schema 定义见 INTERFACES.md。

### 11.2 Pydantic 集成机制

MAF 原生集成 Pydantic——将 Pydantic 模型传给 Agent 的 `output_type` 参数，框架自动提取 JSON schema 并传给模型的 structured output 模式。同时 Pydantic 提供自动验证、类型安全和 IDE 补全。

---

## 十二、关键工程决策

### 12.1 urgency 计算：全部由 LLM 完成

**不需要额外工程实现。** 将 SPEC.md §4.1-4.2 的规则写入 System Prompt instructions，LLM 在推理过程中自行执行。

理由：
1. 1-4 × 1-4 的乘法对强推理模型完全可靠
2. priority/confidence 的赋值本身是语义判断，计算与判断不可分割
3. 避免引入不必要的工具往返
4. 安全网：如需后续验证，可在应用层检查 session_updates 中的 urgency 值是否等于 p×c

### 12.2 context 管理：不做压缩

总 context 预估 ~15-30k tokens（见 SPEC.md §13.2），远小于现代模型 context window（128k-200k+）。研究 Agent 隔离已解决唯一的 context 压力源（50-100k 原始网页数据 → 2-3k 结构化输出）。

Instructions 保持策略规则全集，用阶段标题组织，LLM 根据 session state 的 `stage` 字段自然聚焦当前阶段。

### 12.3 profile 更新时机：推荐完成后先落草稿，恢复时再应用

**触发机制**（系统层自动，非 LLM 判断）：应用调度层在处理 session_updates 时，检测 `recommendation_round` 是否变为 `"完成"`。如果是，自动从 DecisionOutput 的 `profile_updates` 字段提取画像更新数据，写入 session 的 `pending_profile_updates`。

**恢复检查**：下次启动时，应用层先读取当前活跃 session。如存在未应用的 `pending_profile_updates`，则结合 `intent`、`error_state`、收敛状态和 staleness 做一次恢复检查；只有通过检查后，才真正写入长期 profile 文件。

**LLM 的职责**：在 instructions 中规定——"当你将 recommendation_round 设为 '完成' 时，必须同时在 profile_updates 中包含本轮积累的用户画像更新数据"。LLM 不需要判断长期画像何时正式落库。

**intent 规则**：应用层在执行恢复检查和 profile 写入时检查 session 的 `intent` 字段——送礼/纯咨询时跳过或部分更新（详见 SPEC.md §8.3）。

### 12.4 边界保护：应用层直接实现

不使用 MAF 的 middleware 抽象。V1 在应用调度层的主循环中直接做边界检查（详细阈值见 SPEC.md §13.1）。

当前默认限制与 `SPEC.md` 保持一致：
- `dispatch_category_research`：单 session 建议值 2 个不同 category；当已调研 2 个不同品类、准备进入第 3 个不同品类前给出软提示，并要求主 Agent 解释继续调研的必要性
- `dispatch_product_search`：单 session 建议值 6 次，超出后给出软提示而非立即阻断

---

## 十三、决策分工矩阵

以下表格明确列出项目中所有关键决策点——每个决策由 **LLM**（System Prompt 指导）做还是由**系统代码**做。这是 Agent 项目最重要的架构约束之一。

### 13.1 LLM 负责的决策（认知层）

| 决策点 | LLM 做什么 | 输出位置 |
|--------|-----------|---------|
| 任务形态识别 | 判断当前任务属于单品选购、搭配/补齐、升级/换代、跨品类延伸还是纯咨询，并据此决定后续策略 | `internal_reasoning` + `session_updates.decision_progress` |
| urgency 计算（priority × confidence） | 分析用户输入，赋值维度的 priority 和 confidence，计算 urgency | `session_updates.requirement_profile` |
| urgency 阈值判断 | 判断是否有 ≥12 的阻塞维度，是否需要继续追问 | `next_action`（ask_user vs dispatch） |
| 品类和产品类型识别 | 从用户输入判断 category 和 product_type | `session_updates.category/product_type` |
| 当前购物目标 / 当前焦点识别 | 判断当前轮是在围绕整体购物目标推进，还是暂时聚焦某个具体产品类型或子问题 | `session_updates.goal_summary` / `session_updates.product_type` |
| stage 判断 | 判断当前处于哪个业务阶段 | `session_updates.decision_progress.stage` |
| 歧义检测 | 识别模糊表述，触发锚定确认 | `user_message`（追问内容） |
| JTBD 信号识别 | 从用户行为推断功能/情绪/社会需求 | `session_updates.jtbd_signals` |
| intent 识别 | 判断用户意图（自用/送礼/复购/纯咨询） | `session_updates.intent` |
| 推荐产品选择与排序 | 基于需求画像从候选中选择和排序 | `user_message`（推荐内容） |
| 多次搜索拆解与编排 | 对搭配/补齐/升级类任务，判断是否需要拆成多个 research 子问题、分步搜索或先给阶段性建议 | `next_action` + `action_payload` + `user_message` |
| 反事实解释 | 生成"为什么推荐/不推荐"的解释 | `user_message` |
| recommendation_round 推进 | 判断推荐周期是否完成，设置 `"完成"` | `session_updates.decision_progress.recommendation_round` |
| profile_updates 准备 | 在推荐周期完成时准备画像更新数据 | `DecisionOutput.profile_updates` |
| 偏好漂移检测 | 检测用户偏好变化（显式/隐式） | `session_updates`（更新维度）+ `user_message`（确认） |
| 约束冲突检测（语义级） | 在 CoT 中检查硬约束之间是否冲突 | `internal_reasoning` + `user_message`（沟通冲突） |
| 研究结果语义校验 | 检查产品是否匹配硬约束、是否有幻觉迹象 | `internal_reasoning`（校验记录） |
| staleness 恢复决策 | 看到 staleness 标注后决定如何继续 | `user_message` + `next_action` |

### 13.2 系统代码负责的决策（调度层）

| 决策点 | 系统做什么 | 实现位置 |
|--------|-----------|---------|
| 文档选择性加载 | 根据 session 中的 category/product_type 选择加载哪些文件和 section | ContextProviders |
| Onboarding 检测 | 检查 global_profile.json 是否存在 → 注入标注 | ProfileContextProvider |
| 品类文档存在性检测 | 检查 knowledge 文件和 product_type section → 注入标注 | KnowledgeContextProvider |
| next_action 路由 | 根据 action 值执行对应系统动作 | Action Router |
| dispatch payload sanity check | 检查必填字段、空值、基础类型是否合法 | execute_research() 前置校验 |
| session_updates 写入 | 机械性 key 覆盖 | DocumentStore |
| pending_research_result 清除 | 主 Agent 下一轮消费后统一清除 | Action Router 后处理 |
| pending_profile_updates 落盘 | recommendation_round = "完成" 时将 profile_updates 写入 session 草稿区 | 外部循环后置检查 |
| candidate_products 刷新 | dispatch_product_search 后将研究 Agent 初筛结果刷新为活动候选池 | Dispatch 后处理 |
| recommendation_round 自动重置 | dispatch_product_search 后重置为 "未开始" | Dispatch 后处理 |
| 长期画像恢复写入 | 启动时检查 `pending_profile_updates` → 通过恢复规则后写入长期画像 | 启动恢复检查 |
| 搜索策略传递 | 主 Agent 在 dispatch payload 中传 research_brief → 填入 prompt 模板 | execute_research() |
| staleness 检测 | 计算 last_updated 距今天数 → 注入标注 | SessionContextProvider |
| 边界保护 | 检查最大轮数、最大 dispatch 次数 | 外部循环 |
| 研究 Agent 生命周期 | 创建 → 运行 → 销毁 → 后处理 | execute_research() |
| 活跃 session 保留 | current_session 作为运行锚点长期保留；历史 session 默认不进 context | Session 生命周期管理 |
| session_id 生成 | 格式 `{date}-{HHMMSS}` | 新会话创建时 |

### 13.3 分工原则

> **LLM 做认知判断，系统代码做确定性动作。**

判断标准是：这个决策需要**语义理解**吗？
- 需要 → LLM 做（通过 instructions 指导）
- 不需要 → 系统代码做

例外情况：即使是确定性逻辑（如 urgency = priority × confidence），如果该计算与语义判断不可分割（priority 的赋值本身就是语义判断），也由 LLM 一并完成。

**搜索策略决策示例**：
- ❌ 系统层根据 location 硬编码"搜中文/搜英文" → 这是语义判断，应由主 Agent 做
- ✅ 主 Agent 根据 location、用户语言、品类特征等综合判断，生成 research_brief → 系统层只负责填充模板

> [!WARNING]
> **Coding Agent 开发时最常犯的错误**：把应该由系统代码做的事情写进 prompt 让 LLM 判断（如检测文件是否存在），或者把应该由 LLM 判断的事情写成硬编码规则（如 stage 转移条件、搜索语言策略）。务必对照此矩阵。
