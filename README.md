# Shopping Agent

本产品是一个面向复杂消费决策的购物顾问 Agent。主要针对参数繁多、场景差异显著、用户需求往往模糊的消费场景，通过多轮对话，主动挖掘用户真实需求与使用场景，自主构建结构化品类认知，对复杂约束条件进行综合分析，为用户提供可解释的产品选购建议与分析。帮助用户解决在选购产品时，面对海量且真假难辨的信息时的“选择困难”问题。

产品核心不是返回一个搜索结果，而是帮用户把"我大概需要什么"收敛到"我为什么选这个"。系统通过跨会话的四层记忆，积累用户画像和品类知识，目标是形成「越用越懂我」的用户体验。

## 项目定位

Shopping Agent 适用于以下类型的选购场景：

- 品类具备一定客观可比较参数（性能、规格、测试数据等）
- 决策维度多，产品参数多，可选产品多，难以简单快速地做出决策
- 不同使用场景与需求下，适合的产品差异较大
- 用户对参数不熟悉，或难以在一开始就准确表达自己的需求

支持单品选购、搭配补齐、跨品类延伸等多种消费场景，底层共享同一套需求挖掘与研究流程。

## 核心设计

### 1. 1+1 Agent 架构

- **主 Agent**：负责需求理解、阶段判断、推荐解释、偏好更新和下一步动作决策
- **研究 Agent**：负责一次性的外部研究任务，包括品类调研和具体产品搜索

主 Agent 不直接操作工具，只输出结构化决策；工具调用能力由研究 Agent 独立持有，"语义判断"与"系统动作"各有明确归属。

### 2. Agent Harness & 行为控制

应用调度层承担 Agent harness：

- 外部循环管理多轮会话的 Observe → Reason → Act
- `Action Router` 执行 `next_action`，统一处理调研、写入、恢复和降级
- `ContextProviders` 做确定性的上下文注入，明确模型该读取哪些信息
- `DocumentStore` 管理四层记忆的持久化边界

LLM 负责语义判断，系统代码负责确定性逻辑，职责边界在代码层显式划定。

### 3. 四层文档化记忆

运行时状态以本地 JSON 文档为载体，分为四层：

- `knowledge/`：品类领域知识，含决策维度、tradeoff、场景映射
- `user_profile/global_profile.json`：跨品类的宏观用户画像
- `user_profile/category_preferences/`：品类级偏好与选购记录
- `sessions/`：会话状态与决策推进记录

各层生命周期独立，状态可恢复、可检查、可单独演进。

## 项目结构

```text
shopping/
├── src/
│   ├── agents/      # 主 Agent、研究 Sub-Agent、工具与 prompt 装配
│   ├── context/     # Session / Knowledge / Profile 上下文注入
│   ├── models/      # Pydantic 数据模型与结构化输出契约
│   ├── router/      # Action Router，负责 next_action 执行
│   ├── store/       # DocumentStore，负责持久化读写
│   ├── utils/       # 运行时配置、日志、session 辅助逻辑
│   ├── app.py       # 应用调度层 / 外部循环
│   └── cli.py       # CLI 入口
├── data/            # 本地运行数据（session、knowledge、profile）
├── docs/            # 产品、架构、接口、prompt 与任务文档
└── tests/           # 单元测试、 smoke 测试与端到端测试
```

## 技术栈与依赖

- Python 3.13+
- Microsoft Agent Framework（MAF）
- Pydantic
- Tavily
- pytest / pytest-asyncio
- ruff / mypy / uv

LLM 接入采用 OpenAI 标准通用 API 接口，支持共享默认配置与 Agent 专属配置分层覆盖。

## 文档说明

工程文档位于 `docs/`，主要用于指导 Coding Agent 开发：

- `docs/AGENTS.md`：Coding Agent 顶层行为规范
- `docs/SPEC.md`：产品定义、范围边界、验收口径
- `docs/ARCHITECTURE.md`：系统架构、运行模型、职责分工
- `docs/INTERFACES.md`：结构化输出与持久化 Schema
- `docs/PROMPTS.md`：Prompt 设计参考
- `docs/TASKS.md`：实现任务拆解与后续开发顺序

## 当前状态与计划

目前核心工程骨架已建立，涵盖多轮对话主流程、1+1 分层运行模型、结构化输出与动作路由、Tavily 研究搜索链路、四层持久化体系，以及恢复检查、边界保护、错误处理和日志记录。

仍在推进的部分：

- 收口 harness 细节，包括接口、状态流转、错误处理和推荐链路的边界行为
- Web UI：产品设计内的交互界面，替代当前 CLI 交互
- Agent 性能评估：基于需求缺失率、阈值拟合度、推荐采纳率等核心指标，对主 Agent 的决策质量做结构化评估
