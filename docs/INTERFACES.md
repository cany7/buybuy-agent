# INTERFACES.md — 接口契约与数据 Schema

> 本文档定义所有组件间的接口契约：Pydantic 模型（Agent 输出）和 JSON Schema（持久化数据）。是开发文档与实现代码的权威参考；运行时 prompt 文本位于 `src/prompts/`，设计说明位于 `PROMPTS.md`。
>
> **Pydantic vs JSON 分界**：Pydantic 只覆盖 "LLM → 应用层" 的接口（`DecisionOutput`、`CategoryResearchOutput`、`ProductSearchOutput`）。持久化数据（session / knowledge / profile）使用 Plain JSON dict，Schema 在本文档中定义为文档约定。
>
> **关于示例数据**：本文档中的示例使用了多个品类（户外装备、数码产品、智能家居等）来说明数据结构。这些示例仅为说明性案例，系统不限制品类范围，适用于任何符合产品定位的消费品类。

---

## 一、Pydantic 模型（Agent 输出接口）

### 1.1 主 Agent 输出：`DecisionOutput`

主 Agent 每轮对话的结构化输出。通过 MAF 的 `output_type` 参数传入，LLM 的输出被强制约束为此结构。

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional


class DimensionUpdate(BaseModel):
    """单个维度的更新记录（仅用于 InternalReasoning，不是 session state 中的维度格式）"""
    dimension: str
    value: Optional[str] = None
    priority: int = Field(ge=1, le=4)
    confidence: int = Field(ge=1, le=4)
    urgency: int = Field(ge=1, le=16)
    update_reason: str


class InternalReasoning(BaseModel):
    """Agent 的内部推理记录（系统层不消费，用于 debug 和指标）"""
    state_summary: str
    updated_dimensions: list[DimensionUpdate] = []
    blocking_dimensions: list[str] = []       # urgency >= 12
    uncertain_dimensions: list[str] = []      # urgency 8-11
    jtbd_observations: Optional[str] = None
    stage_assessment: str


class DecisionOutput(BaseModel):
    """主 Agent 每轮对话的结构化输出"""

    # 给用户看的回复
    user_message: str

    # Agent 内部推理过程
    internal_reasoning: InternalReasoning

    # 系统层消费的决策
    next_action: Literal[
        "ask_user",
        "dispatch_category_research",
        "dispatch_product_search",
        "recommend",
        "onboard_user",
    ]

    # dispatch 时的任务描述 / onboard_user 时的 demographics
    action_payload: Optional[dict] = None

    # 需要更新的 session state sections（section 级替换）
    session_updates: Optional[dict] = None

    # 推荐周期完成时的画像更新草稿
    # 仅当 recommendation_round 设为 "完成" 时填充
    # 应用层先将其写入 session.pending_profile_updates
    # 真正写入 profile 文件发生在下次启动恢复检查时
    # 内部结构见 §2.4
    profile_updates: Optional[dict] = None
```

> [!IMPORTANT]
> **`internal_reasoning` 的设计意图**：系统层不消费此字段内容——它的价值是：
> 1. **强制 LLM 每轮执行完整的思考流程**（urgency 计算、阈值检查、stage 评估），而非跳过推理直接输出决策
> 2. **debug 和指标分析**——可以离线检查 LLM 的推理是否合理

### 1.2 研究 Agent 输出：`CategoryResearchOutput`

品类调研任务的输出。结构直接映射到品类知识文档 Schema（§3.1），研究 Agent 产出的数据可直接写入 `knowledge/{category}.json`，不需要应用层做格式转换。

```python
class SharedConcept(BaseModel):
    """跨产品类型的通用概念"""
    name: str
    description: str
    relevant_product_types: list[str]


class BrandInfo(BaseModel):
    """品牌信息"""
    brand: str
    positioning: str
    known_for: str


class ProductTypeOverview(BaseModel):
    """产品类型概览条目"""
    product_type: str
    subtypes: list[str]
    description: str


class CategoryKnowledge(BaseModel):
    """品类级通用知识"""
    data_sources: list[str]
    product_type_overview: list[ProductTypeOverview]
    shared_concepts: list[SharedConcept]
    brand_landscape: list[BrandInfo]


class DecisionDimension(BaseModel):
    """决策维度"""
    name: str
    objectivity: str = Field(description="可量化 | 半量化 | 主观")
    importance: str = Field(description="高 | 中 | 低")
    ambiguity_risk: str = Field(description="高 | 中 | 低")
    ambiguity_note: Optional[str] = None


class Tradeoff(BaseModel):
    """维度间 tradeoff"""
    dimensions: list[str]
    explanation: str


class PriceTier(BaseModel):
    """价位段"""
    range: str
    typical: str
    features: str


class ScenarioMapping(BaseModel):
    """场景映射"""
    scenario: str
    key_needs: list[str]
    can_compromise: list[str]


class Misconception(BaseModel):
    """常见误区"""
    misconception: str
    reality: str
    anchor_suggestion: str


class ProductTypeKnowledge(BaseModel):
    """产品类型级知识"""
    subtypes: dict[str, str]
    decision_dimensions: list[DecisionDimension]
    tradeoffs: list[Tradeoff]
    price_tiers: list[PriceTier]
    scenario_mapping: list[ScenarioMapping]
    common_misconceptions: list[Misconception]


class CategoryResearchOutput(BaseModel):
    """品类调研任务的结构化输出"""
    category: str
    category_knowledge: CategoryKnowledge
    product_type_name: str
    product_type_knowledge: ProductTypeKnowledge
    notes: Optional[str] = None    # 调研过程说明/缺失信息标注
```

> [!NOTE]
> 应用层后处理时将 `product_type_knowledge` 写入 `knowledge/{category}.json` 的 `product_types.{product_type_name}` 路径下。

### 1.3 研究 Agent 输出：`ProductSearchOutput`

产品搜索任务的输出。

```python
class PriceInfo(BaseModel):
    """价格信息。保留展示文本，必要时附带币种和可比较数值。"""
    display: str
    currency: Optional[str] = None
    amount: Optional[float] = None   # 仅当来源给出明确单值时填写


class ProductInfo(BaseModel):
    """单个产品的结构化信息"""
    name: str
    brand: str
    price: PriceInfo
    specs: dict
    features: list[str]       # 产品功能/特点的完整介绍（必须详尽）
    pros: list[str]
    cons: list[str]
    sources: list[str]        # 信息来源 URL 列表
    source_consistency: str = Field(description="high | medium | low")


class SearchMeta(BaseModel):
    """产品搜索任务的结构化运行元信息"""
    retry_count: int
    result_status: Literal["ok", "insufficient_results", "partial_results", "failed"]
    search_expanded: bool
    expansion_notes: Optional[str] = None


class ProductSearchOutput(BaseModel):
    """产品搜索任务的结构化输出"""
    products: list[ProductInfo] = []
    search_meta: SearchMeta                     # 搜索执行元信息（固定结构，供应用层稳定消费）
    notes: str                                  # 搜索过程说明/限制
    suggested_followup: Optional[str] = None    # 建议主 Agent 注意的点
```

> [!IMPORTANT]
> **`features` 字段必须包含产品功能/特点的完整介绍**，确保主 Agent 在后续对话中不需要为了回答"这款的 XX 功能怎么样"而重新发起搜索。这是研究 Agent prompt 模板中的硬性要求。
>
> **`price` 字段使用结构化对象而非单一 `float`**：这样既能保留原始价格展示文本，也能兼容不同币种、区间价格、MSRP/到手价差异，以及“暂缺精确价格”的场景。若来源给出明确单值，可在 `amount` 中提供便于比较的数值；否则至少保留 `display`。
>
> **`search_meta` 是应用层记录搜索运行状态的结构化来源**，避免从 `notes` 自由文本中反推重试次数、结果状态或是否放宽搜索范围。它是 `ProductSearchOutput` 的固定子模型，至少包含以下核心字段：
> - `retry_count`: `int`
> - `result_status`: `"ok" | "insufficient_results" | "partial_results" | "failed"`
> - `search_expanded`: `bool`
> - `expansion_notes`: `str | null`
>
> 其中：
> - `retry_count` 和 `search_expanded` 由应用层视实际运行过程做规范化，不能简单假设为模型自报 telemetry
> - `result_status` 可由研究 Agent 给出初始判断，但应用层保留根据降级和后处理进行规范化的权利

---

## 二、`action_payload` 约定

`DecisionOutput.action_payload` 保持为 `Optional[dict]`（不做 Pydantic 子模型），因为其结构依赖于 `next_action` 的值。以下为每种 action 对应的 payload 文档约定：

| next_action | action_payload 结构 |
|-------------|---------------------|
| `ask_user` | `None` |
| `recommend` | `None` |
| `dispatch_category_research` | 见 §2.1 |
| `dispatch_product_search` | 见 §2.2 |
| `onboard_user` | 见 §2.3 |

### 2.1 `dispatch_category_research` payload

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| category | string | 是 | 品类名称 |
| product_type | string | 是 | 产品类型 |
| user_context | string | 是 | 用户背景信息 |
| research_brief | string | 否 | 搜索策略提示（自然语言），例如"优先看英文权威评测，再补中文用户经验"。若不提供，研究 Agent 按默认策略执行 |

**示例**：
```json
{
  "category": "户外装备",
  "product_type": "冲锋衣",
  "user_context": "男性用户，28岁，上海，具体需求未知",
  "research_brief": "以中文搜索为主，英文搜索为辅。中文搜索关键词应包含产品名称、评测、推荐等；英文搜索关键词用于补充国际评测源。"
}
```

### 2.2 `dispatch_product_search` payload

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| product_type | string | 是 | 产品类型 |
| search_goal | string | 是 | 搜索目标描述 |
| constraints | object | 是 | 约束条件（见下表） |
| research_brief | string | 否 | 搜索策略提示（自然语言） |

**constraints 字段**：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| budget | string \| null | 否 | 预算范围（如 "2500-3500"）或 null/"unspecified" |
| gender | string | 否 | 性别偏好 |
| key_requirements | list[string] | 是 | 核心需求列表 |
| scenario | string | 否 | 使用场景 |
| exclusions | list[string] | 否 | 排除项（品牌/产品） |

**示例**：
```json
{
  "product_type": "冲锋衣",
  "search_goal": "搜索适合周末徒步和4000m级高海拔的冲锋衣",
  "constraints": {
    "budget": "2500-3500",
    "gender": "男款",
    "key_requirements": ["高防水（用户有淋雨经历，不能是基础防水）", "兼顾透气"],
    "scenario": "周末徒步+偶尔4000m级高海拔",
    "exclusions": ["国产品牌"]
  },
  "research_brief": "优先看英文权威评测，再补中文用户经验。如果国际型号和国内型号不同，请标出差异。"
}
```

> [!NOTE]
> - `product_type`、`search_goal`、`constraints.key_requirements` 为最低必要信息
> - `budget` 为**可选约束字段**：若当前任务预算未知、非阻塞，或用户明确要求先不看预算，可显式传 `null` 或 `"unspecified"`
> - `budget` 可能是区间（如 "2500-3500"）而非单一数字，应用层**不尝试做数值解析**
> - `exclusions` 传递用户在 session 或 category_preferences 中已表达的排斥偏好（`anti_preferences`），由主 Agent 在 CoT 中综合两个来源写入
> - `research_brief` 由主 Agent 根据 location、用户语言、品类特征等综合判断后填写，用于表达高层搜索偏好
> - 系统层仍负责 Tavily 工具装配、预算上限、失败重试和降级，不把 `research_brief` 当作唯一控制面

### 2.3 `onboard_user` payload

```json
{
  "demographics": {
    "gender": "男",
    "age_range": "25-30",
    "location": "上海"
  }
}
```

### 2.4 `profile_updates` 结构

`DecisionOutput.profile_updates` 保持为 `Optional[dict]`。仅当 `recommendation_round` 被设为 `"完成"` 时填充。应用层先将其原样写入 `session.pending_profile_updates`，在下次启动恢复检查通过后，再根据顶层 key 分别写入不同文件：

```json
{
  "global_profile": {
    "consumption_traits": {
      "overall_tendency": "愿意为高频使用场景投入预算",
      "brand_attitude": "对国际品牌有信任感",
      "decision_style": "研究型",
      "novelty_preference": "偏好成熟验证的产品"
    },
    "lifestyle_tags": ["户外运动", "周末徒步"]
  },
  "category_preferences": {
    "consumption_traits": {
      "category_tendency": "愿意为品质溢价",
      "preferred_brands": [
        { "brand": "Arc'teryx", "reason": "综合品质认可" }
      ],
      "anti_preferences": [
        { "item": "国产品牌", "reason": "品牌信任度不足" }
      ]
    },
    "primary_scenarios": ["周末徒步", "高海拔登山"],
    "purchase_history": [
      {
        "product_type": "冲锋衣",
        "date": "2026-04-12",
        "chosen_product": "Arc'teryx Beta LT",
        "key_decision_factors": ["防水性能", "品牌信任"]
      }
    ]
  }
}
```

> [!IMPORTANT]
> - `profile_updates` 的第一落点是 `sessions/current_session.json` 中的 `pending_profile_updates`，不是本轮立即写入长期画像
> - `global_profile` 下的字段 → 在恢复检查通过后写入 `user_profile/global_profile.json`
> - `category_preferences` 下的字段 → 在恢复检查通过后写入 `user_profile/category_preferences/{category}.json`（`category` 从 session state 中读取）
> - 两个顶层 key 均为可选——如果某次推荐没有产生可更新的全局画像信息，可以只包含 `category_preferences`
> - `category_preferences.consumption_traits.preferred_brands[*].reason` 和 `anti_preferences[*].reason` 均为**可选字段**——如果用户只表达了偏好/排斥对象，没有明确原因，可以省略
> - `profile_updates` 是目标持久化文档的**同构片段**：字段名必须与目标文件 schema 保持一致，不额外引入中间命名

---

## 三、JSON Schema（持久化数据）

以下 Schema 定义持久化到 `data/` 目录的 JSON 文件结构。应用层对这些文件只做机械性读写（key 覆盖），不做 Pydantic 建模。

### 3.1 品类知识文档 — `knowledge/{category}.json`

文档分两层：`category_knowledge`（品类级，始终加载）和 `product_types.*`（产品类型级，按需加载）。

```json
{
  "category": "[大品类名称]",
  "last_updated": "[日期]",

  "category_knowledge": {
    "data_sources": ["[来源列表]"],
    "product_type_overview": [
      {
        "product_type": "[产品类型名称]",
        "subtypes": ["[子类型1]", "[子类型2]"],
        "description": "[一句话描述]"
      }
    ],
    "shared_concepts": [
      {
        "name": "[跨产品类型的通用概念/技术/材料名称]",
        "description": "[说明]",
        "relevant_product_types": ["[适用的产品类型列表]"]
      }
    ],
    "brand_landscape": [
      {
        "brand": "[品牌名]",
        "positioning": "[品牌在该品类中的定位]",
        "known_for": "[品牌特点]"
      }
    ]
  },

  "product_types": {
    "[产品类型名称]": {
      "subtypes": {
        "[子类型名]": "[子类型特点描述]"
      },
      "decision_dimensions": [
        {
          "name": "[维度名称]",
          "objectivity": "可量化 | 半量化 | 主观",
          "importance": "高 | 中 | 低",
          "ambiguity_risk": "高 | 中 | 低",
          "ambiguity_note": "[歧义说明，仅当 ambiguity_risk 为高/中时填写]"
        }
      ],
      "tradeoffs": [
        {
          "dimensions": ["[维度A]", "[维度B]"],
          "explanation": "[此消彼长的原因]"
        }
      ],
      "price_tiers": [
        {
          "range": "[价格区间]",
          "typical": "[典型品牌/产品]",
          "features": "[该价位段特点]"
        }
      ],
      "scenario_mapping": [
        {
          "scenario": "[使用场景名称]",
          "key_needs": ["[该场景下的关键需求]"],
          "can_compromise": ["[该场景下可妥协的点]"]
        }
      ],
      "common_misconceptions": [
        {
          "misconception": "[常见误解]",
          "reality": "[实际情况]",
          "anchor_suggestion": "[锚定确认建议]"
        }
      ]
    }
  }
}
```

### 3.2 用户宏观画像 — `user_profile/global_profile.json`

```json
{
  "last_updated": "2026-04-10",
  "demographics": {
    "age_range": "25-30",
    "gender": "男",
    "location": "北京",
    "consumption_level": "中等偏上",
    "occupation_hint": "互联网从业者"
  },
  "consumption_traits": {
    "overall_tendency": "视品类而定",
    "decision_style": "深度研究型",
    "brand_attitude": "对知名品牌有信任感，但不盲目追捧",
    "novelty_preference": "偏好成熟验证的产品"
  },
  "lifestyle_tags": [
    "周末户外活动爱好者",
    "摄影爱好者"
  ],
  "notes": [
    "用户对产品有一定了解，但可能混淆细分品类概念"
  ]
}
```

> [!NOTE]
> `demographics` 中的 `gender`、`age_range`、`location` 由 onboarding 写入（`onboard_user` action），其余字段由推荐完成后生成草稿，并在下次启动恢复检查通过后写入。

### 3.3 品类偏好 — `user_profile/category_preferences/{category}.json`

```json
{
  "category": "户外装备",
  "last_updated": "2026-04-10",
  "consumption_traits": {
    "category_tendency": "愿意为品质溢价",
    "preferred_brands": [
      { "brand": "Arc'teryx", "reason": "品质信任" }
    ],
    "anti_preferences": [
      { "item": "某品牌X", "reason": "之前有过质量问题" }
    ]
  },
  "primary_scenarios": [
    "周末徒步",
    "偶尔3000m以上高海拔"
  ],
  "purchase_history": [
    {
      "product_type": "冲锋衣",
      "chosen_product": "Arc'teryx Beta LT",
      "key_decision_factors": ["防水性能", "品牌信任"],
      "date": "2026-03"
    }
  ],
  "profile_source": {
    "is_native": true,
    "migrated_from": null
  }
}
```

> [!IMPORTANT]
> - **`anti_preferences`（排斥偏好）作为独立字段存在**，负面信号（"绝对不要XX"）往往比正面信号更稳定、筛选价值更高
> - `preferred_brands[*].reason` 和 `anti_preferences[*].reason` 为**可选字段**；如果没有明确原因，只记录 `brand` / `item` 本身即可
> - **画像迁移机制**：在新品类中使用从其他品类迁移的偏好时，`is_native` 标记为 `false`，相关维度 confidence 统一标为 4（未确认）

### 3.4 会话状态 — `sessions/current_session.json`

```json
{
  "session_id": "2026-04-10-143052",
  "last_updated": "2026-04-10T14:30:52",
  "intent": "自用选购",
  "product_type": "冲锋衣",
  "category": "户外装备",

  "decision_progress": {
    "stage": "候选探索",
    "stage_note": "允许非线性跳转，这是标签而非严格状态机",
    "current_blocker": "使用场景的具体强度未明确",
    "next_action": "锚定确认使用场景强度",
    "recommendation_round": "未开始"
  },

  "requirement_profile": {
    "basic_info": [
      {
        "dimension": "预算",
        "value": "3000-4000",
        "priority": 4,
        "confidence": 1,
        "urgency": 4,
        "source": "用户明确表示"
      },
      {
        "dimension": "使用场景",
        "value": "周末徒步+偶尔高海拔",
        "priority": 4,
        "confidence": 2,
        "urgency": 8,
        "source": "用户表述但'高海拔'未锚定确认"
      }
    ],
    "dimension_weights": [
      {
        "dimension": "防水",
        "sub_dimension": "防水指数",
        "priority": 4,
        "confidence": 3,
        "urgency": 12,
        "source": "场景推断(徒步+高海拔)"
      },
      {
        "dimension": "透气",
        "sub_dimension": "透气性",
        "priority": 3,
        "confidence": 3,
        "urgency": 9,
        "source": "场景推断"
      }
    ]
  },

  "jtbd_signals": {
    "functional": ["防水防风保护", "徒步舒适性"],
    "emotional": ["不想买错后悔"],
    "social": [],
    "dominant": "功能为主"
  },

  "error_state": {
    "constraint_conflicts": [],
    "search_retries": 0,
    "consecutive_negative_feedback": 0,
    "validation_warnings": [],
    "events": []
  },

  "goal_summary": "为周末徒步补齐一套基础外层装备",
  "existing_items": ["已有登山鞋", "已有软壳"],
  "missing_items": ["硬壳冲锋衣", "30L背包"],

  "pending_research_result": {
    "type": "product_search",
    "result": { "...": "ResearchOutput 原始结果" }
  },

  "pending_profile_updates": {
    "global_profile": { "...": "等待恢复检查后应用的画像草稿" },
    "category_preferences": { "...": "等待恢复检查后应用的画像草稿" }
  },

  "candidate_products": {
    "products": [
      { "...": "研究 Agent 初筛后的候选产品，结构同 ProductInfo" }
    ],
    "notes": "搜索过程说明/限制",
    "suggested_followup": "建议后续关注的差异点",
    "last_refreshed": "2026-04-12T10:30:00"
  }
}
```

**Session State 核心顶层字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 格式 `{date}-{HHMMSS}`，如 `"2026-04-10-143052"` |
| `last_updated` | string | ISO 时间戳，应用层每轮写入时自动更新 |
| `intent` | string | 用户意图（自用选购/送礼/复购/纯咨询） |
| `product_type` | string | 当前轮的主要产品焦点；在搭配/补齐/升级类任务中，它表示当前顺序推进到的单个子问题，可随编排过程变化，但同一时刻只表示一个当前焦点 |
| `category` | string | 当前咨询的大品类 |
| `decision_progress` | object | 决策推进状态（stage / blocker / recommendation_round） |
| `requirement_profile` | object | 需求画像快照（basic_info + dimension_weights） |
| `jtbd_signals` | object | JTBD 三层信号（functional / emotional / social） |
| `error_state` | object | 错误追踪（冲突 / 重试 / 负面反馈 / 校验警告） |

**Session State 可选运行时顶层字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `goal_summary` | string | 当前购物目标的自然语言摘要；当任务是搭配/补齐/升级/跨品类延伸时，它是比 `product_type` 更高层的主锚点 |
| `existing_items` | list[string] | 当前任务直接相关的已拥有物品，仅按需记录 |
| `missing_items` | list[string] | 当前任务直接相关的待补缺项，仅按需记录 |
| `pending_research_result` | object | 研究 Agent 输出的一次性交接结果，系统在主 Agent 完成下一轮消费后清除 |
| `pending_profile_updates` | object | 推荐完成后生成的长期画像更新草稿，等待下次启动恢复检查决定是否正式应用 |
| `candidate_products` | object | 当前推荐周期的活动候选池，承载当前研究焦点下的产品搜索初筛结果；在搭配/补齐类任务中，它始终只对应当前焦点的候选，不承担多子问题并行保留或跨焦点统一比较的职责 |

**`error_state` 扩展结构**：

```json
{
  "constraint_conflicts": [],
  "search_retries": 0,
  "consecutive_negative_feedback": 0,
  "validation_warnings": [],
  "events": []
}
```

> 固定核心字段用于统计和验收；额外异常事件（如 `insufficient_results`、`partial_search_result`、`search_failed`）统一进入 `events` 数组。

**`pending_research_result` 结构**：

```json
{
  "type": "category_research | product_search",
  "result": { "..." }
}
```

**`candidate_products` 结构**：

```json
{
  "products": [{ "...": "ProductInfo" }],
  "search_meta": {
    "retry_count": 1,
    "result_status": "insufficient_results",
    "search_expanded": true,
    "expansion_notes": "已补充新的关键词组合并扩大来源覆盖后再次搜索"
  },
  "notes": "[搜索说明]",
  "suggested_followup": "[可选的后续建议]",
  "last_refreshed": "[ISO 时间戳]"
}
```

> [!NOTE]
> - `candidate_products` 保存的是**研究 Agent 初筛后的候选池**（数量取决于候选质量，不设硬性最小值）
> - 它不是主 Agent 当轮已推荐给用户的 3-5 款子集
> - 对单品任务，它通常对应一个产品类型的候选池；对搭配/补齐类任务，它可以随着当前焦点变化被多次刷新，但**一次只保留当前焦点的一批候选**
> - V1 的多目标任务按“单焦点顺序推进”设计：`candidate_products` 不承载多个 product_type 的并行候选池，也不负责跨焦点回看与统一排序
> - 它由系统在 `dispatch_product_search` 后处理时刷新，不通过 `session_updates` 由 LLM 写入

**`pending_profile_updates` 结构**：

```json
{
  "global_profile": { "...": "可选" },
  "category_preferences": { "...": "可选" }
}
```

> 该字段是 `DecisionOutput.profile_updates` 的 session 内草稿副本。系统在下次启动恢复检查时，根据 intent / error_state / 收敛情况决定是否真正写入长期画像。

**`session_updates` 白名单 key**：`intent`、`product_type`、`category`、`decision_progress`、`requirement_profile`、`jtbd_signals`、`error_state`、`goal_summary`、`existing_items`、`missing_items`。应用层收到 `DecisionOutput.session_updates` 后，仅对白名单内的 key 执行覆盖写入；`pending_research_result`、`pending_profile_updates` 和 `candidate_products` 为系统管理字段，不在白名单中。白名单校验作用于 **`session_updates` 输入**，不作用于已经合并完成的完整 session state。

> [!WARNING]
> **`requirement_profile` 中的维度格式** ≠ **`DimensionUpdate` Pydantic 模型**。
> - Session state 中的 `basic_info` / `dimension_weights` 是 **Plain JSON**，包含 `source`、`sub_dimension` 等字段
> - `DimensionUpdate` 是 §1.1 中定义的 Pydantic 模型，仅用于 `InternalReasoning.updated_dimensions`（推理记录），包含 `update_reason` 字段
> - 两者承载不同用途：前者是持久化的需求状态，后者是单轮推理日志

---

## 四、DocumentStore 核心接口

```python
class DocumentStore:
    """本地 JSON 文件 CRUD。所有路径基于 data/ 目录。"""

    # ━━━ Session ━━━
    def load_session() -> Optional[dict]
    def save_session(state: dict) -> None
    def list_historical_sessions() -> list[dict]
    def apply_pending_profile_updates(session: dict) -> bool

    # ━━━ Knowledge ━━━
    def load_knowledge(category: str, product_type: str = None) -> Optional[dict]
        """选择性加载。返回 category_knowledge + 指定 product_type section（如请求）"""
    def save_knowledge(category: str, data: dict) -> None
        """新建品类文档"""
    def merge_product_type(category: str, product_type: str, data: dict) -> None
        """向已有品类文档增量合并新的 product_type section"""

    # ━━━ Profile ━━━
    def load_global_profile() -> Optional[dict]
    def save_global_profile(updates: dict) -> None
    def load_category_preferences(category: str) -> Optional[dict]
    def save_category_preferences(category: str, updates: dict) -> None
```

> [!NOTE]
> 这些接口为最小必要设计。V1 实现中，所有方法都是对 `data/` 目录下 JSON 文件的 `json.load()` / `json.dump()` 操作，不涉及数据库。
>
> - `save_session(state)` 保存的是**完整 session state**。`session_updates` 的白名单校验应在应用层把增量更新合并进 session 之前完成，而不是在 `save_session()` 内部完成。
> - `apply_pending_profile_updates(session)` 表示恢复检查中的系统步骤：读取 `pending_profile_updates`，根据恢复规则决定是否写入长期画像，返回是否已应用。
> - 历史 session 可以长期保留；是否另存为历史文件属于实现细节，但不再是“推荐完成即自动归档”的默认行为。

---

## 五、数据目录结构

```
data/
├── sessions/
│   ├── current_session.json
│   └── {session_id}.json
├── knowledge/
│   └── {category}.json
└── user_profile/
    ├── global_profile.json
    └── category_preferences/
        └── {category}.json
```

文件名规范：
- `category` 使用简洁中文通用名（如 `户外装备`、`数码电子`）
- `session_id` 使用 `{date}-{HHMMSS}` 格式（如 `2026-04-10-143052`）
