# TESTING.md — 测试策略

> 本文档定义购物推荐 Agent 的测试策略，涵盖传统测试（单元、集成）和 Agent 项目特有的 AI 行为测试。
>
> **核心差异**：Agent 项目的测试不是验证"输出等于什么值"，而是验证"行为是否符合预期模式"。LLM 的输出具有不确定性，因此测试体系需要围绕**行为特征**而非精确值来设计。

---

## 一、测试层次总览

```
┌────────────────────────────────────────────────────────────────────┐
│                    5. 端到端会话测试                                 │
│    完整多轮对话场景：验证全流程是否产生预期的用户体验                    │
├────────────────────────────────────────────────────────────────────┤
│                    4. AI 行为测试（Prompt Evaluation）               │
│    给定 context + 用户输入 → 验证 DecisionOutput 的行为特征             │
├────────────────────────────────────────────────────────────────────┤
│                    3. 集成测试                                      │
│    多组件协作：外部循环、dispatch 后处理、session 保留与恢复            │
├────────────────────────────────────────────────────────────────────┤
│                    2. 单元测试                                      │
│    单组件正确性：DocumentStore、ContextProvider、Action Router 等      │
├────────────────────────────────────────────────────────────────────┤
│                    1. 模型测试                                      │
│    Pydantic 模型验证：字段约束、序列化、边界值                         │
└────────────────────────────────────────────────────────────────────┘
```

| 层次 | 验证对象 | 是否涉及 LLM | 运行频率 |
|------|---------|--------------|---------|
| 模型测试 | Pydantic 模型字段约束 | 否 | 每次代码变更 |
| 单元测试 | 各组件逻辑 | 否 | 每次代码变更 |
| 集成测试 | 组件间协作 | 否（mock LLM） | 每次功能变更 |
| AI 行为测试 | LLM 决策质量 | **是** | Prompt/instructions 变更时 |
| 端到端会话测试 | 完整用户体验 | **是** | 里程碑验收时，及 Prompt/关键流程变更后的回归验证 |

---

## 二、模型测试

### 2.1 Pydantic 模型验证

> 源文档：INTERFACES.md §一

**测试目标**：确保 Pydantic 模型的字段约束正确生效，序列化/反序列化无误。

| 测试用例 | 验证内容 | 预期结果 |
|---------|---------|---------|
| `DimensionUpdate` priority 范围 | `priority=0` 和 `priority=5` | 抛出 ValidationError |
| `DimensionUpdate` confidence 范围 | `confidence=0` 和 `confidence=5` | 抛出 ValidationError |
| `DimensionUpdate` urgency 范围 | `urgency=0` 和 `urgency=17` | 抛出 ValidationError |
| `DecisionOutput` 必填字段 | 缺少 `user_message` 或 `next_action` | 抛出 ValidationError |
| `DecisionOutput.next_action` 枚举约束 | 传入未定义 action（如 `search_products`） | 抛出 ValidationError |
| `DecisionOutput` 可选字段默认值 | 不传 `action_payload`、`session_updates`、`profile_updates` | 默认为 `None` |
| `PriceInfo` 最小实例化 | 仅传 `display` | 成功创建实例 |
| `PriceInfo` 扩展实例化 | 传 `display + currency + amount` | 成功创建实例 |
| `ProductInfo` 完整实例化 | 传入所有必填字段（`price` 为结构化对象） | 成功创建实例 |
| `ProductSearchOutput` 空列表 | `products=[]` | 允许（搜索无结果时的合法状态） |
| `CategoryResearchOutput` 序列化 | 完整实例 → `.model_dump()` → JSON | JSON 结构正确 |

---

## 三、单元测试

### 3.1 DocumentStore

> 源文档：INTERFACES.md §四、ARCHITECTURE.md §6.2-6.4

| 测试用例 | 验证内容 | 预期结果 |
|---------|---------|---------|
| Session CRUD | 创建、读取、更新、保留 | 文件正确读写 |
| `save_session` 自动更新时间 | 写入后检查 `last_updated` | 时间戳已更新 |
| `session_updates` 白名单 key | 应用层合并前传入非白名单 key | 被拒绝/忽略 |
| 系统管理临时字段 roundtrip | `save_session()` 处理含 `pending_research_result` / `pending_profile_updates` / `candidate_products` 的 state | 不做隐式清理或推断 |
| `apply_pending_profile_updates(session)` | 恢复检查流程 | 根据恢复规则正确应用或跳过 |
| Knowledge 选择性加载 | `load_knowledge("户外装备", "冲锋衣")` | 仅返回 `category_knowledge` + 冲锋衣 section |
| Knowledge 增量合并 | 已有冲锋衣，合并登山鞋 | 冲锋衣 section 不受影响 |
| Knowledge 文件不存在 | `load_knowledge("不存在的品类")` | 返回 `None` |
| Profile 创建 | `save_global_profile(...)` 文件不存在时 | 新建文件 |
| Profile section 级替换 | 只更新 `consumption_traits` | `demographics` 不受影响 |
**测试策略**：使用临时目录（`tempfile.mkdtemp()`）作为 `data/` 目录，测试后清理。

### 3.2 ContextProviders

> 源文档：ARCHITECTURE.md §七、PROMPTS.md §三

#### SessionContextProvider

| 测试用例 | 验证内容 | 预期结果 |
|---------|---------|---------|
| 正常加载 | 有活跃 session | 输出包含 session state 文本 |
| 有 pending_research_result | session 中有待消费的研究结果 | 输出包含 `"## 研究结果（待消费）"` 区块 |
| 无活跃 session | `current_session.json` 为空 | 创建新 session，包含 `session_id` |
| 搭配任务上下文 | session 中有 `goal_summary` / `existing_items` / `missing_items` | 输出包含这些轻量上下文 |
| Staleness 检测 | `last_updated` 超过 7 天 | 输出包含 `"[系统标注] 会话已暂停"` |
| Staleness + pending_research | 超期且有未消费结果 | 标注包含过期提醒 |
| 常规每轮路径 | session 含 `pending_profile_updates` | ContextProvider 本身不触发恢复检查 |

#### KnowledgeContextProvider

| 测试用例 | 验证内容 | 预期结果 |
|---------|---------|---------|
| 品类文档存在 + product_type 存在 | 加载单个 product_type | 输出包含 `category_knowledge` + 该 product_type |
| 品类文档存在 + product_type 缺 | 品类有但无当前产品类型 | 输出包含通用知识 + 系统标注 `"需要产品类型调研"` |
| 品类文档不存在 | knowledge 中无对应文件 | 输出包含系统标注 `"需要品类调研"` |
| product_type 列表注入 | 文档有多个 product_types | 输出包含已有产品类型名称列表 |

#### ProfileContextProvider

| 测试用例 | 验证内容 | 预期结果 |
|---------|---------|---------|
| 新用户 | `global_profile.json` 不存在 | 输出包含系统标注 `"新用户，请先执行轻量 onboarding"` |
| demographics 不完整 | `global_profile.json` 存在但缺 `gender` / `age_range` / `location` 任一字段 | 输出包含系统标注 `"新用户，请先执行轻量 onboarding"` |
| 已有用户 | `global_profile.json` 存在 | 输出包含用户画像 |
| 有品类偏好 | `category_preferences/{category}.json` 存在 | 输出包含品类偏好 |
| 无品类偏好 | 对应品类偏好文件不存在 | 不报错，不注入品类偏好 |

### 3.3 Action Router

> 源文档：ARCHITECTURE.md §十

| 测试用例 | 验证内容 | 预期结果 |
|---------|---------|---------|
| `ask_user` 路由 | `next_action="ask_user"` | 返回 `user_message`，流程等待用户输入 |
| `recommend` 路由 | `next_action="recommend"` | 行为同 `ask_user` |
| `dispatch_product_search` 路由 | 合法 payload | 调用 `execute_research()`，后处理正确 |
| `dispatch_product_search` 路由（预算可空） | `constraints.budget = null / unspecified` | 仍视为合法 payload |
| `dispatch_category_research` 路由 | 合法 payload，包含 `user_context` | 调用 `execute_research()`，知识文档写入 |
| `onboard_user` 路由 | 包含 demographics | demographics 写入 `global_profile.json` |
| 非法 `next_action` | 不在枚举中的值 | 记录错误，不崩溃 |
| 非法 payload 格式 | `dispatch_product_search` 缺少必要字段 | 记录错误，不崩溃 |
| `candidate_products` 刷新 | `dispatch_product_search` 后处理 | 保存 research agent 初筛候选池 |
| `pending_research_result` 清除 | 上一轮存在 pending 且本轮已消费 | 后置检查后被移除 |
| 后置检查：画像草稿 | `recommendation_round` 从非完成变为 `"完成"` | 写入 `pending_profile_updates` 草稿 |
| 恢复检查：送礼 | `intent="送礼"` 且存在 `pending_profile_updates` | 跳过自用画像更新 |
| `recommendation_round` 重置 | `dispatch_product_search` 后处理 | 重置为 `"未开始"` |

### 3.4 边界保护

| 测试用例 | 验证内容 | 预期结果 |
|---------|---------|---------|
| 最大轮数 | 第 30 轮后 | 提示用户并保留当前 session |
| 品类调研上限 | 第 3 次 `dispatch_category_research` | 拒绝新的品类调研 |
| 产品搜索建议次数 | 第 7 次 `dispatch_product_search` | 给出软提示 |
| 阈值可配置 | 修改配置值 | 按新阈值执行 |

---

## 四、集成测试

> 使用 mock LLM 输出，测试多组件协作的正确性。不验证 LLM 的决策质量（那是 AI 行为测试的职责）。

### 4.1 外部循环完整流程

**测试方法**：构造一系列预设的 `DecisionOutput` 序列，mock 主 Agent 的返回值，验证应用调度层的行为。

| 测试用例 | Mock 输出序列 | 验证内容 |
|---------|-------------|---------|
| 基本对话循环 | `ask_user` × 3 | session state 每轮更新，用户消息正确返回 |
| Dispatch 流程 | `ask_user` → `dispatch_product_search` → `recommend` | 研究 Agent 被调用 → pending_research_result 设置 → candidate_products 刷新 → 下一轮消费 → 清除 pending |
| 多目标任务流程 | `ask_user` → `dispatch_product_search` → `recommend` → `dispatch_product_search` → `recommend` | 同一购物目标下允许多次搜索；`goal_summary` / `existing_items` / `missing_items` 保持连续；`candidate_products` 可被刷新后继续复用 |
| 推荐完成生成画像草稿 | `recommend`（recommendation_round="完成"，含 profile_updates） | `pending_profile_updates` 被写入 session |
| 重启后应用画像草稿 | 启动时发现未应用的 `pending_profile_updates` | 恢复检查通过后更新 global_profile 和 category_preferences |
| Onboarding → 正常对话 | `onboard_user` → `ask_user` → ... | demographics 写入后正常对话继续 |

### 4.2 Dispatch 后处理链路

| 测试用例 | 验证内容 |
|---------|---------|
| 品类调研后处理 | 知识文档正确创建/合并 + `pending_research_result` 设置 |
| 产品搜索后处理 | `pending_research_result` 设置 + `candidate_products` 刷新 + `recommendation_round` 重置 |
| 多次产品搜索后处理 | 连续两次 `dispatch_product_search` | 新一轮 research 结果正确覆盖 `pending_research_result`，`candidate_products` 按当前研究焦点刷新，`recommendation_round` 每次都重置 |
| 研究 Agent 返回空结果 | 不崩溃，`pending_research_result` 包含空结果 + notes |
| payload sanity check | payload 缺少必填字段时不调用研究 Agent |

### 4.3 Session 保留与恢复流程

| 测试用例 | 验证内容 |
|---------|---------|
| 退出后保留 current session | `current_session.json` 保持存在且内容完整 |
| 下次启动恢复检查 | 发现 `pending_profile_updates` 时先执行恢复判断 |
| 历史 session 不默认注入 | 有历史 session 文件时，常规对话不自动加载 |

---

## 五、AI 行为测试（Prompt Evaluation）

> **核心理念**：给定特定的 context 和用户输入，验证 LLM 输出的 `DecisionOutput` 是否展现预期的**行为特征**——不验证精确的文本内容或数值，而是验证决策模式。

### 5.1 评估框架

#### 评估流程

```
1. 构造测试场景（context + user_input）
2. 调用主 Agent，获取 DecisionOutput
3. 对 DecisionOutput 的关键字段进行行为断言
4. 多次运行取一致性（同一场景跑 3 次，至少 2 次通过）
```

#### 行为断言类型

| 断言类型 | 检查方法 | 示例 |
|---------|---------|------|
| **Action 正确性** | `next_action` 是否为预期值 | 品类不存在时应 `dispatch_category_research` |
| **维度更新方向** | `internal_reasoning.updated_dimensions` 中某维度的 priority/confidence 变化方向 | 用户说"预算3000" → 预算维度 confidence 值应变小（趋向 1=确定，如从 4 变为 1） |
| **阻塞维度检测** | `internal_reasoning.blocking_dimensions` 是否包含/不包含特定维度 | 所有核心维度已讨论后 → blocking 应为空 |
| **Stage 合理性** | `session_updates.decision_progress.stage` 是否为合理值 | 需求已明确 → stage 不应仍是 "需求挖掘" |
| **消息质量** | `user_message` 中是否包含/不包含特定模式 | 锚定确认时应提供具体选项而非接受模糊表述 |
| **Payload 完整性** | `action_payload` 包含必要字段 | dispatch_product_search 的 constraints 应包含已讨论的维度 |

### 5.2 核心评估用例

#### 5.2.1 urgency 计算与阈值判断

> 源文档：SPEC.md §4.1-4.2

| 场景 ID | 场景描述 | 预期行为 |
|---------|---------|---------|
| URG-01 | 所有核心维度 confidence=4（全未知） | `next_action="ask_user"`，批量提问 |
| URG-02 | priority=4 × confidence=4 的维度存在 | `blocking_dimensions` 非空 |
| URG-03 | 用户回答覆盖多个维度后无 urgency≥12 | `next_action` 应为 `dispatch_product_search` 或继续非阻塞性提问 |
| URG-04 | 4 个维度的 urgency 在 8-11 区间 | 应触发针对性追问（中等不确定性累积规则）|
| URG-05 | priority≤2 且 confidence=4 的维度 | **不应**出现在 `blocking_dimensions` 中 |

**验证方法**：
```python
# URG-02 示例
context = build_context(
    session_state={"requirement_profile": {"dimension_weights": [
        {"dimension": "使用场景", "priority": 4, "confidence": 4, "urgency": 16},
        {"dimension": "预算", "priority": 4, "confidence": 4, "urgency": 16}
    ]}},
    knowledge=hardcoded_jacket_knowledge
)
result = main_agent.run(context + "想买一件冲锋衣")
assert len(result.internal_reasoning.blocking_dimensions) > 0
assert result.next_action == "ask_user"
```

#### 5.2.2 歧义检测与锚定确认

> 源文档：SPEC.md §4.4

| 场景 ID | 用户输入 | 预期行为 |
|---------|---------|---------|
| AMB-01 | "要在高海拔穿的" | `user_message` 中应包含具体化选项（如具体海拔范围） |
| AMB-02 | "经常出差，需要比较轻便的" | `user_message` 应确认"轻便"的具体标准 |
| AMB-03 | "预算大概3000元左右" | **不应**触发歧义确认（已足够具体） |
| AMB-04 | "专业级的那种" | `user_message` 中应有锚定确认 |

**验证方法**：检查 `user_message` 中是否包含具体化的选项或数字，而非简单接受模糊表述。

#### 5.2.3 Stage 判断

> 源文档：SPEC.md §3.1

| 场景 ID | 当前状态 | 预期 Stage / Action |
|---------|---------|-------------------|
| STG-01 | 品类知识不存在 | `dispatch_category_research` |
| STG-02 | 品类知识存在，需求未明确 | stage="需求挖掘"，`ask_user` |
| STG-03 | 需求已明确，无阻塞维度 | `dispatch_product_search` |
| STG-04 | 产品数据已返回 | stage="候选探索"，`recommend` |
| STG-05 | 推荐完成，用户做出选择 | recommendation_round="完成" |

#### 5.2.4 Onboarding

> 源文档：SPEC.md §3.3

| 场景 ID | Context | 预期行为 |
|---------|---------|---------|
| ONB-01 | context 包含 onboarding 标注 + 用户说"想买冲锋衣" | 先执行 onboarding 提问（性别/年龄/城市），暂缓品类需求 |
| ONB-02 | context 包含 onboarding 标注 + 用户回答了 demographics | `next_action="onboard_user"`，`action_payload` 包含 demographics |
| ONB-03 | context 无 onboarding 标注 | 不触发 onboarding |

#### 5.2.5 偏好漂移识别

> 源文档：SPEC.md §4.5

| 场景 ID | 用户行为 | 预期行为 |
|---------|---------|---------|
| DRF-01 | 之前说预算3000，现在看到5000的产品说"这个也不错" | 进行偏好确认（而非直接更新） |
| DRF-02 | 直接说"预算可以提到5000" | 直接更新预算维度（显式漂移） |
| DRF-03 | 维度被第4次修改 | `user_message` 应包含需求总结确认 |

#### 5.2.6 Intent 识别

> 源文档：SPEC.md §九

| 场景 ID | 用户输入 | 预期 Intent |
|---------|---------|------------|
| INT-01 | "想给爸爸买个生日礼物" | `intent="送礼"` |
| INT-02 | "想了解一下相机" | `intent="纯咨询"` |
| INT-03 | "我的冲锋衣穿了5年想换了" | `intent="复购/换代"` |
| INT-04 | "想买一件冲锋衣" | `intent="自用选购"` |

#### 5.2.7 推荐策略

> 源文档：SPEC.md §七

| 场景 ID | 阶段 | 预期行为 |
|---------|------|---------|
| REC-01 | 第一轮推荐 | 推荐 3-5 款产品，`user_message` 主动请用户反馈 |
| REC-02 | 第二轮 - 用户有新偏好 | 基于已有候选重新排序分析（不重新搜索） |
| REC-03 | 第二轮 - 候选不适用 | `next_action="dispatch_product_search"`（重新搜索） |
| REC-04 | 第二轮 - 提供反事实解释 | `user_message` 包含"为什么不推荐XX"类说明 |
| REC-05 | 搭配/补齐任务 - 目标尚未收敛 | 可先给阶段性建议或购买优先级，不要求强行产出单品式最终推荐 |
| REC-06 | 搭配/补齐任务 - 当前焦点切换 | 可围绕同一 `goal_summary` 重新聚焦新的 `product_type`，并再次 `dispatch_product_search` |

#### 5.2.8 任务形态识别与多目标编排

> 源文档：SPEC.md §1.4、§3.4、§7.1；ARCHITECTURE.md §13.1

| 场景 ID | 用户输入 / 当前状态 | 预期行为 |
|---------|-------------------|---------|
| TSK-01 | "帮我补齐一套周末徒步装备" | 不直接压缩成单一产品；应识别为搭配/补齐任务，并在 session 中写入 `goal_summary` |
| TSK-02 | 用户已说明"已有登山鞋和软壳，还缺外层和背包" | `session_updates` 包含 `existing_items` / `missing_items`，而不是要求完整 inventory |
| TSK-03 | 当前已完成外层搜索，用户继续问"那背包呢？" | 可保持同一购物目标，切换当前 `product_type` 焦点并再次 `dispatch_product_search` |
| TSK-04 | 同一购物目标下已经进行过一次推荐，但用户要求先定购买顺序 | 可输出阶段性建议 / 优先级排序，而不是被迫直接结束推荐周期 |

#### 5.2.9 语义级约束冲突检测

> 源文档：SPEC.md §10.1

| 场景 ID | 用户输入 / 当前状态 | 预期行为 |
|---------|-------------------|---------|
| CFL-01 | 预算明显低于满足硬需求的最低价位 | 不输出 `dispatch_product_search`，先向用户解释冲突并给出取舍方案 |
| CFL-02 | 两个 priority=4 的硬约束存在明确 tradeoff 冲突 | 不输出 `dispatch_product_search`，先做教育性解释 |
| CFL-03 | 无冲突，仅存在少量非阻塞不确定性 | 可以输出 `dispatch_product_search` |

### 5.3 研究 Agent 评估

> 需要实际调用 LLM 执行搜索任务，评估输出质量。

| 测试用例 | 验证内容 | 目标 |
|---------|---------|------|
| 品类调研完整性 | `CategoryResearchOutput` 的所有子结构是否非空 | 关键字段填充率 ≥ 80% |
| 产品搜索广度 | `ProductSearchOutput.products` 长度 | 数量仅作参考；优先验证匹配度与诚实性，允许少量高匹配候选或空列表并附原因说明 |
| `features` 充分性 | 每个 `ProductInfo.features` 的条目数 | 每个产品 ≥ 3 条 features |
| `source_consistency` 合理性 | 标注值与实际来源数量是否一致 | sources 仅 1 个时不应标 high |
| 无幻觉 | 检查产品名+品牌组合是否真实存在 | 抽查验证 |
| Schema 一致性 | 输出是否通过 Pydantic 校验 | 通过率 100% |

### 5.4 评估执行规范

#### 运行频率

| 触发条件 | 执行范围 |
|---------|---------|
| System Prompt 变更 | 全部 AI 行为测试 |
| 新增 instructions 规则 | 相关场景的 AI 行为测试 |
| Phase 里程碑 | 全部 AI 行为测试 + 端到端 |
| 研究 Agent prompt 变更 | 研究 Agent 评估用例 |

#### 一致性策略

由于 LLM 输出具有不确定性，每个评估用例运行 **3 次**：
- 3/3 通过 → ✅ 通过
- 2/3 通过 → ⚠️ 基本通过（记录失败 case 供分析）
- 1/3 或 0/3 通过 → ❌ 失败（需修改 prompt）

---

## 六、端到端会话测试

> 完整多轮对话场景，验证全流程从用户体验维度的正确性。手动执行或半自动化（预设用户输入序列）。
>
> **定位说明**：本节场景是 `TASKS.md` 里程碑验收完成后的持久测试用例，用于 Prompt、instructions 或关键流程变更后的回归验证；它们不是对里程碑冒烟测试的重复要求，而是后续持续维护的行为证据。

### 6.1 场景 A：完整 Happy Path

> 源文档：SPEC.md §14.2 场景 A

**测试流程**：新用户 × 新品类（冲锋衣）× 全流程

```
用户输入序列：
1. "想买一件冲锋衣"
2. [回答 onboarding：性别/年龄/城市]
3. [等待品类调研完成]
4. [回答批量提问：场景/预算/偏好]
5. [回答锚定确认]
6. [等待产品搜索完成]
7. [对推荐产品给出反馈]
8. [做出最终选择]
```

**验证检查清单**：
- [ ] Onboarding 正确执行（新用户检测 → demographics 收集）
- [ ] 品类调研正确触发（知识文档不存在 → dispatch）
- [ ] 知识文档正确创建（`knowledge/户外装备.json`）
- [ ] 批量提问（非逐维度轮询）
- [ ] 歧义锚定确认（模糊表述被具体化）
- [ ] 阈值判断正确（信息充足后推进）

### 6.2 场景 B：搭配 / 补齐任务与多次搜索

> 源文档：SPEC.md §3.4、§7.1、§11.3

**测试流程**：已有基础装备 × 补齐剩余装备 × 同一购物目标下多次搜索

```
用户输入序列：
1. "想补齐一套周末徒步装备"
2. [回答已有物品：已有登山鞋和软壳，还缺冲锋衣和背包]
3. [回答预算与场景]
4. [等待第一次产品搜索完成：先搜冲锋衣]
5. [对第一轮建议反馈：先把外层定下来]
6. [继续追问：那背包呢？]
7. [等待第二次产品搜索完成：转向背包]
8. [获得阶段性建议：先买什么、后买什么]
```

**验证检查清单**：
- [ ] 主 Agent 识别为搭配/补齐任务，而不是立即压缩成唯一单品
- [ ] session 中正确记录 `goal_summary`、`existing_items`、`missing_items`
- [ ] 同一购物目标下允许两次 `dispatch_product_search`
- [ ] 第二次搜索前，`product_type` 焦点可以切换，但 `goal_summary` 保持连续
- [ ] `candidate_products` 在第二次搜索后按当前研究焦点刷新
- [ ] 输出可以是阶段性建议 / 购买优先级，而不是强行给出单品式终局推荐
- [ ] 产品搜索正确触发
- [ ] `candidate_products` 在第一轮推荐后仍保留，第二轮可复用
- [ ] 两轮推荐均已执行
- [ ] `recommendation_round` 正确流转（未开始→第一轮→第二轮→完成）
- [ ] `pending_profile_updates` 在"完成"时被正确写入
- [ ] 下次启动恢复检查后，`global_profile.json` 和 `category_preferences/户外装备.json` 被创建/更新
- [ ] Session 在推荐完成后仍被保留，可用于恢复

### 6.2 场景 B：回退场景

> 源文档：SPEC.md §14.2 场景 B

**测试流程**：推荐阶段发现新需求 → 重新搜索

```
用户输入序列：
1-6. [同场景 A 至第一轮推荐完成]
7. "这几个都不太满意，我想要看起来很专业的那种"
8. [回答锚定确认"专业"的含义]
9. [等待重新搜索]
10. [对新推荐列表反馈]
```

**验证检查清单**：
- [ ] 新需求维度正确添加到 session
- [ ] 歧义触发锚定确认
- [ ] 正确判断需要重新搜索（非在已有候选分析）
- [ ] 如果无明确新需求，第二轮优先复用 `candidate_products` 而非重复搜索
- [ ] `recommendation_round` 被重置（系统在 dispatch 后自动重置）
- [ ] 新搜索条件包含更新后的需求

### 6.3 场景 C：老用户场景

> 源文档：SPEC.md §14.2 场景 C

**测试流程**：已有用户画像 + 已有品类知识 → 新产品类型

**前置条件**：需先完成场景 A，确保 `global_profile`、`category_preferences/户外装备.json`、`knowledge/户外装备.json` 已存在。

```
用户输入序列：
1. "想买双登山鞋"
2. [回答登山鞋特有需求]
```

**验证检查清单**：
- [ ] 不触发 Onboarding
- [ ] `category_knowledge` 复用（不重建整个文档）
- [ ] 仅补充新 product_type section（`product_types.登山鞋`）
- [ ] 不加载无关的 `product_types.冲锋衣` section
- [ ] 已有画像被读取，减少重复提问
- [ ] 需求挖掘轮次显著减少

### 6.4 场景 D：错误恢复

> 源文档：SPEC.md §14.2 场景 D

**验证检查清单**：
- [ ] 搜索结果不足时不崩溃
- [ ] 向用户透明沟通限制
- [ ] 提供下一步建议
- [ ] `error_state` 正确记录

---

## 七、评估指标采集

> 源文档：SPEC.md §14.1

### 7.1 四个核心指标

| 指标 | 计算方法 | 数据来源 | 目标值 |
|------|---------|---------|--------|
| **需求缺失率** | 推荐阶段新浮现的 priority≥3 维度数 / 总关键维度数 | Session 日志：阶段 4 中用户提出的新需求 | < 15% |
| **阈值拟合度** | 回退率 = 阶段 3→2 + 阶段 4→2 的回退次数 / 总阈值判断次数 | Session stage 流转日志 | 回退率 < 20% |
| **推荐采纳率** | 用户表示正面兴趣的产品数 / 第一轮推荐产品数 | 用户反馈的情感分析 | 第一轮 ≥ 40% |
| **搜索效率** | waste_rate = (搜索返回数 - 推荐引用数) / 搜索返回数 | 研究 Agent 输出 vs 推荐引用 | waste_rate < 40% |

### 7.2 指标采集方法

```
数据来源：data/sessions/session_log.jsonl

每轮日志条目：
{
    "timestamp": "...",
    "turn": 5,
    "user_input": "...",
    "decision_output": { ... },  // 完整 DecisionOutput
    "action_executed": "ask_user",
    "stage_before": "需求挖掘",
    "stage_after": "需求挖掘",
    "errors": []
}
```

**离线分析脚本**：会话结束后，从 JSONL 日志中提取：
1. Stage 流转序列 → 计算回退率
2. 阶段 4 中 `updated_dimensions` 里新增的 priority≥3 维度 → 计算需求缺失率
3. 第一轮推荐的产品列表 vs 用户反馈 → 计算采纳率
4. 研究 Agent 返回产品数 vs 推荐中引用的产品数 → 计算搜索效率

### 7.3 日志格式约定

- 文件格式：JSONL（每行一个 JSON 对象）
- 文件位置：`data/sessions/session_log.jsonl`
- 每轮产生一条记录
- 日志仅追加写入，不修改历史记录
- 会话生命周期内，对应的日志段可通过 `session_id` 关联

---

## 八、测试工具与环境

### 8.1 技术栈

| 用途 | 工具 |
|------|------|
| 单元测试框架 | `pytest` |
| Mock | `unittest.mock` / `pytest-mock` |
| 临时文件 | `tempfile.mkdtemp()` |
| 异步测试 | `pytest-asyncio` |
| 覆盖率（可选） | `pytest-cov` |

### 8.2 测试目录结构

```
tests/
├── unit/
│   ├── test_models.py           # Pydantic 模型测试
│   ├── test_document_store.py   # DocumentStore 单元测试
│   ├── test_context_providers.py # ContextProvider 单元测试
│   └── test_action_router.py    # Action Router 单元测试
├── integration/
│   ├── test_external_loop.py    # 外部循环集成测试（mock LLM）
│   ├── test_dispatch_flow.py    # Dispatch 后处理链路
│   └── test_session_lifecycle.py # Session 生命周期
├── eval/
│   ├── test_urgency.py          # urgency 行为评估
│   ├── test_ambiguity.py        # 歧义检测评估
│   ├── test_stage.py            # Stage 判断评估
│   ├── test_onboarding.py       # Onboarding 评估
│   ├── test_recommendation.py   # 推荐策略评估
│   ├── test_research_agent.py   # 研究 Agent 输出评估
│   └── conftest.py              # 共用 fixtures（context 构造、知识文档加载等）
├── e2e/
│   ├── scenarios.py             # 端到端场景定义（用户输入序列）
│   └── test_happy_path.py       # 完整流程验证
└── conftest.py                  # 全局 fixtures
```

### 8.3 Mock 策略

| 测试层 | LLM Mock 方式 |
|--------|--------------|
| 单元测试 | 完全 mock，不涉及 LLM |
| 集成测试 | 用预设的 `DecisionOutput` 实例 mock `main_agent.run()` 返回值 |
| AI 行为测试 | **真实调用 LLM**——这是测试 Prompt 质量的核心 |
| 端到端测试 | **真实调用 LLM** |

> [!WARNING]
> AI 行为测试和端到端测试会产生 LLM API 调用费用。建议在 Prompt 变更时批量执行，避免每次 CI 触发。
