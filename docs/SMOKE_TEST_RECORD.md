# SMOKE_TEST_RECORD.md

## 2026-04-15

### Phase 1 CLI Smoke
- 脚本：`tests/test_phase1_smoke.py`
- 执行命令：`uv run pytest tests/test_phase1_smoke.py`
- 场景：基于冲锋衣 Happy Path 的最小 CLI 闭环，使用真实 `run_cli()`、`ShoppingApplication`、`ActionRouter`、`DocumentStore`，并以固定主 Agent/研究结果替身稳定复现 3 轮以上对话和一次 `dispatch_product_search`
- 运行时准备：
  - 将 `tests/fixtures/户外装备.json` 复制到临时 `data/knowledge/户外装备.json`
  - 在临时 `data/user_profile/global_profile.json` 写入 demographics，保证当前 Phase 1 代码可直接进入需求挖掘与搜索主路径
- 验证结果：
  - CLI 正常启动并打印欢迎语
  - 输入 `"想买一件冲锋衣"` 后可正常进入多轮对话
  - 对话至少持续 3 轮，`current_session.json` 持续写入并记录多个快照
  - `dispatch_product_search` 成功触发，研究返回结构化 `ProductSearchOutput`
  - 搜索后的 `candidate_products`、`pending_profile_updates`、`recommendation_round` 均按约定落盘
  - 运行过程中无未处理异常
- 备注：该冒烟测试为确定性脚本，避免依赖真实外部 LLM/API 凭证；用于验证当前 Phase 1 主路径的系统集成与状态流转。
