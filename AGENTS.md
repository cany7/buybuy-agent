# AGENTS.md

本文件面向在仓库根目录及其子目录内工作的 Coding Agent。目标是降低误改、重复定义、接口漂移，以及把规划态内容误当成现实实现的风险。

## 作用范围

本文件适用于整个仓库。若某个子目录后续新增更深层的 AGENTS.md，以更深层文件为准。

若本文件与当前任务中的显式要求冲突，以当前任务要求为准。

## 项目当前口径

当前仓库已完成主要开发文档整理，并开始按文档逐步落地实现。

工作时以 docs/ 下文档和仓库实际存在的文件树为准，不假设规划中的目录、模块或运行入口已经实现，也不要为了“贴合设计图”主动创建与当前任务无关的代码骨架。

## 当前仓库导航

当前仓库导航以已存在文件为准。优先查阅以下文档：

- docs/SPEC.md：产品行为、范围边界、验收口径
- docs/ARCHITECTURE.md：架构职责、运行模型、状态流转
- docs/INTERFACES.md：Pydantic 模型、JSON Schema、接口契约
- docs/PROMPTS.md：Prompt 约束
- docs/TASKS.md：实现顺序、依赖关系、阶段任务
- docs/TESTING.md：测试与评估
- docs/CHANGELOG.md：开发与文档变更记录

当仓库新增稳定代码目录、可运行入口或更细粒度测试入口后，再补充本节；不要提前写入尚不存在的目录说明。

## 先看哪份文档

不要凭经验补全架构，不要把其他项目的常见模式直接套进来。遇到不确定之处，按下面顺序查证：

- 产品行为、范围边界、验收口径：docs/SPEC.md
- 架构职责、运行模型、状态流转：docs/ARCHITECTURE.md
- Pydantic 模型、JSON Schema、接口契约：docs/INTERFACES.md
- Prompt 约束：docs/PROMPTS.md
- 实现顺序、依赖关系、阶段任务：docs/TASKS.md
- 测试与评估：docs/TESTING.md

AGENTS.md 只定义高价值协作约束，不重复充当架构文档、接口文档或完整实现说明。

## 当前操作入口

当前仓库尚未形成稳定的应用启动入口。除非当前任务明确要求，否则不要假设存在 main.py、服务启动脚本、CLI 入口或自定义 task runner。

当前默认操作入口仅包括环境准备与验证命令：

uv sync
uv run pytest
uv run ruff check .
uv run mypy .

若后续仓库新增实际可运行入口，以 pyproject.toml、.github/workflows/、实际脚本文件为准，再更新本节；不要自行发明命令体系。

## 开始改动前

开始任何实现或修改前，先做下面几件事：

- 先确认当前任务对应的 source of truth 文档
- 先确认仓库现实状态，而不是只看规划目录
- 只读取和当前任务直接相关的章节
- 明确本次改动会影响哪些代码、文档、测试
- 涉及接口、状态流转、Prompt、Schema 的改动，默认检查是否需要联动更新文档和测试

## 高价值约束

### 1. 接口与 Schema 以 docs/INTERFACES.md 为准

DecisionOutput、研究输出、持久化字段、next_action 合法值及其 payload 结构，统一以 docs/INTERFACES.md 为准。

实现时不要自行增加字段名、状态名、枚举值或 payload 结构，也不要在 prompt 或代码里再维护一份平行 schema。

### 2. 主 Agent 与系统职责边界以 docs/ARCHITECTURE.md 为准

主 Agent 负责基于 context 做语义判断并输出结构化结果，不直接承担系统动作、持久化写入、文件读写、路由分发、恢复检查等职责。

不要把本应由系统代码实现的确定性逻辑塞进 prompt、Agent 工具或模型输出约定里。

### 3. 持久化读写由应用层和 store 层统一管理

不要让 Agent 直接读写持久化文件，尤其不要绕过应用层直接修改 data/ 下内容。

Agent 只能通过结构化输出表达意图，例如：

- session_updates
- action_payload
- profile_updates

具体写入时机、覆盖规则和恢复流程，以 docs/ARCHITECTURE.md 与 docs/INTERFACES.md 为准。

### 4. 不要把规划态实现当成现实状态

文档中的目标结构用于指导实现顺序，不代表仓库已具备对应目录、模块、入口或测试覆盖。

除非当前任务明确要求，不要为了追求“理想结构”主动铺设整套骨架、预建空目录，或补写与当前任务无关的占位代码。

### 5. 机密信息只放环境变量

不要把 API keys、token、真实账号、外部服务密钥写进代码、测试样例或提交到仓库。

配置集中到统一配置模块或 .env，不要引入新的环境管理方式。

## 当前已知实现约束

### Python 与工具链

以 pyproject.toml 为准：

- Python: >=3.13
- 开发工具：pytest、pytest-asyncio、ruff、mypy
- 环境与命令约定：uv

若后续仓库新增更准确的脚本入口、任务别名或 CI 约束，以实际仓库配置为准。

## 改动时的实现原则

### 先服从当前现实，再考虑目标结构

文档中的目标结构可以指导未来实现，但当前任务应优先贴合仓库现状。

没有落地的目录不要当成已存在；没有实现的模块不要当成可调用；没有稳定入口不要自行假定运行方式。

### 确定性逻辑放系统代码

这类逻辑默认放系统层，不写进 prompt 代替代码：

- 文件存在性检测
- onboarding 触发判断
- 路由分发
- payload 基本校验
- 持久化写入
- 恢复检查
- 边界保护

### 语义判断放 LLM

这类判断默认由模型完成，不要硬编码成简单规则：

- 任务形态识别
- 需求澄清与歧义识别
- stage 判断
- 推荐解释
- 偏好漂移识别
- 是否需要追加搜索

## 代码风格

- 保持类型注解完整
- 优先使用清晰的小函数和单一职责模块
- 字符串优先使用 f-string
- MAF 异步调用使用 async/await
- 不吞异常；捕获后记录日志并做明确降级
- JSON 读写使用 UTF-8，写入时使用可读缩进，并保留中文

## 什么时候必须同步改别处

遇到下面这些改动，默认认为不能只改一个文件：

### 修改 DecisionOutput 或研究输出模型

同步检查：

- docs/INTERFACES.md
- 实现代码
- 相关测试
- 必要时 docs/PROMPTS.md

### 修改 next_action 或其 payload

同步检查：

- docs/INTERFACES.md
- docs/ARCHITECTURE.md
- docs/PROMPTS.md
- 路由代码
- 相关测试

### 修改 session / knowledge / profile 的 Schema

同步检查：

- docs/INTERFACES.md
- 相关 store / context / app 代码
- 相关测试

### 修改 Prompt 规则

同步检查：

- docs/PROMPTS.md
- 实现中的 prompt / instructions
- 相关行为测试

### 修改开发流程或协作约束

同步检查：

- 本文件
- 相关文档
- 必要的示例或流程说明

## 最低验证要求

按改动类型执行最小验证，不要改完就停：

- 仅文档修改：检查术语、交叉引用、章节一致性
- 接口或 Schema 修改：检查实现、文档、测试是否同步
- Prompt 修改：至少做一轮手动场景验证
- 代码实现：至少运行与改动直接相关的测试或最小冒烟验证
- 涉及外部循环或状态流转：至少检查 session 相关状态是否符合文档约定

## 提交前检查

提交前至少确认：

- 改动符合当前任务所依赖的 source of truth
- 没有把规划态信息误写成现实状态
- 没有引入未定义字段、枚举或状态名
- 没有把系统职责偷渡给 Agent、prompt 或工具层
- 必要的文档和测试已经同步更新

## 协作记录

当改动影响行为、接口、协作约束、开发流程或文档口径时，更新 docs/CHANGELOG.md，至少记录：

- 日期
- 操作类型
- 涉及文件
- 做了什么
- 必要时补充原因或下一步

纯局部重构、无行为变化的测试修复、注释调整，可不强制记录。

## 不该做的事

- 不要把 AGENTS.md 写成完整架构说明书
- 不要在这里重复维护完整 schema
- 不要默认仓库已经具备规划中的所有目录
- 不要绕过应用层直接改持久化文件
- 不要为了“顺手”引入新的环境管理方式
- 不要在文档和代码之间制造双份 source of truth