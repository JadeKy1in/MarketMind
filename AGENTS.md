# MarketMind — 给所有 AI 编程助手的说明

适用于 Codex、Claude Code、Cursor 等任何 AI 工具。Claude Code 另读 `CLAUDE.md`，两者内容一致；冲突时以 `docs/SPEC_v3.md` 为准。

## 开工前必读

1. `docs/SPEC_v3.md`：唯一事实来源。第 13 节是施工顺序，§13.1 是开放问题。
2. 各阶段设计稿：`docs/S2_DESIGN.md` 至 `docs/S6_DESIGN.md`（后续阶段按同样命名）。
3. 本文件的"未完成事项"。
4. `PROGRESS_v3.md` 只存在于所有人本机、不入库。如果你看不到它，以本文件和 SPEC 为准。

## 约定（与 CLAUDE.md 相同）

- **import**：只用 `from marketmind.xxx import ...`，在仓库根目录运行。
- **数字由代码产生**：价格、指标、仓位、止损由代码计算。LLM 只负责解读和写文字，输出必须经过 schema 或边界校验。
- **不吞异常**：关键路径至少记日志并标注降级。
- **测试**：必须能离线跑完（`python -m pytest marketmind/tests -q -p no:warnings`）。访问网络的测试打 `slow` 标记，默认跳过。
- **可结算**：任何预测或建议都写进统一账本（`marketmind/ledger/`）。
- **分支**：在 `v3` 上开发，`master` 保持原样。全量测试通过后直接 `git push origin v3:v3`。
- **密钥**：只从环境变量读取，不打印，不提交。
- **交流**：所有人偏好中文、简洁；需要确认的事在对话里问，不要让所有人去读 md 文件。

## 未完成事项（做完后从这里删除）

- [ ] **odds_analyst（预测市场赔率影子）：暂缓，未放弃，必须补上。**
  - 卡点：需要 Kalshi / Polymarket 的公开赔率。2026-09 所有人在利雅得，当地网络屏蔽这两个站（疑为博彩类政策）。所有人决定不绕过当地法规：不用代理，也不用云端代抓。
  - 恢复条件：所有人本机能直接访问这两个 API 时（例如回国后）。
  - 做法与步骤：见 `docs/SPEC_v3.md` §13.1；代码位置是 `marketmind/shadows/v3/roster.py` 里的 odds_analyst 条目。
- [ ] **Robinhood 加密货币只读持仓同步**（SPEC L2 唯一允许的券商接口）：需要所有人在 Robinhood 申请加密 API 密钥后再做；在此之前持仓用 `python -m marketmind.holdings add` 手动录入（见 `docs/S6_DESIGN.md`）。
- [ ] **证据层背离清单喂给主管线**（SPEC §5 第 1 步）：S5 只做到"写文件 + 进账本 + 仪表盘"，还没有进入 L1 / 决策的输入；需所有人确认后再接。
- [ ] 旧影子生态（ShadowMother 链路约 28 个模块）只在 `legacy_ecosystem_enabled=True` 时运行，是否整体删除待所有人决定。
- [ ] 施工顺序中尚未开始的阶段：S7–S9（见 SPEC §13）。S7 需要账本攒满 60 个交易日。
