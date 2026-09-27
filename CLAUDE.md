# MarketMind — 开发须知

个人项目，所有人与 AI 协作开发。开发任何功能前，先读：
1. `docs/SPEC_v3.md`：唯一事实来源，第 13 节是施工顺序；
2. `PROGRESS_v3.md`（本地文件，不入库）：当前阶段、已完成、待办、阻塞。

`docs/archive/` 下的旧文档只作参考。它们与 SPEC_v3 冲突时，以 SPEC_v3 为准。旧文档里宣称的"COMPLETE"多数不可信（见 `docs/PROJECT_REVIEW_2026-09-27.md`）。

## 约定

- **import**：只用 `from marketmind.xxx import ...`，不要用 `pipeline.*`、`api.*` 这类裸写法。裸写法会把同一个模块加载两份，导致状态分裂。在仓库根目录运行，或把仓库根加入 `sys.path`。
- **数字由代码产生**：价格、指标、仓位、止损、概率校准都由代码计算，LLM 只负责解读与生成文字（SPEC L3）。LLM 的输出必须经过 schema 或边界校验才能使用。
- **不吞异常**：关键路径禁止 `except Exception: pass`，至少记录日志并标注降级。
- **测试**：必须能离线跑完；访问网络的测试打上 `slow` 标记或用 vcr 录制；`slow` 测试默认跳过，设 `MARKETMIND_LIVE_TESTS=1` 才运行（会花真实 token）。所有 LLM 调用都走 `marketmind/gateway/async_client.py`。
- **可结算**：任何预测或建议都要写进统一账本，包含标的、方向、持有期、确信度、可证伪条件（SPEC §7）。
- **分支**：在 `v3` 上开发，`master` 保持原样。每完成一个阶段，**先问所有人**，再推送到 GitHub。
- **密钥**：只从环境变量读取，不打印，不提交。

## 交流

- 所有人偏好中文、简洁；需要确认的事项直接在对话里提问，不要让所有人去读 md 文件。
