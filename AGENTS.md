# MarketMind — 给所有 AI 编程助手的说明

适用于 Codex、Claude Code、Cursor 等任何 AI 工具。Claude Code 另读 `CLAUDE.md`，两者内容一致；冲突时以 `docs/SPEC_v3.md` 为准。

## 开工前必读

1. `docs/SPEC_v3.md`：唯一事实来源。第 13 节是施工顺序，§13.1 是开放问题。
2. 各阶段设计稿：`docs/S2_DESIGN.md` 至 `docs/S8_DESIGN.md`、`docs/S9_DESIGN.md`（自进化第 0 步：账本记录模型与 prompt 版本、代码计算的复盘事实；后续步骤的外部调研结论与参考文献）、`docs/S10_DESIGN.md`（冷门数据发现链：异常扫描、已反映度、观察名单、来源归因；后续阶段按同样命名）。自动运行见 `docs/AUTOMATION.md`。
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
- [ ] **证据层背离清单喂给主管线**（SPEC §5 第 1 步）：所有人 2026-09-28 决定先不接，等背离记录在账本里结算、证明有用后再接。
- [ ] **S8 剩余部分**：警报框架已完成（`docs/S8_DESIGN.md`，观察模式）；顾问（S7 毕业影子写入 `data/advisors.json` 后自动转正式模式并推送）、Playground 接回未做。推送渠道：Server酱（微信）已配置（用户环境变量 `SERVERCHAN_SENDKEY`），2026-09-28 测试消息所有人已收到。
- [ ] **S7 代码已完成**（`docs/S7_DESIGN.md`）：晋升阶梯与四类临时影子每天运行；真正的晋升评审要等账本攒满 60 个交易日（约 2026-12），届时核对第一批正式 / 顾问是否合理。
- [ ] S9 自进化：第 0 步数据基础已完成（`docs/S9_DESIGN.md`）；校准、复盘、认知库、知识继承在约 50–100 条已结算预测前冻结（SPEC §11），启用前按设计稿第 5 节的调研结论设计并由所有人确认。
- [ ] **Bluesky：暂缓，等网络允许再做**（所有人 2026-09-30 决定）。
  - 泄露的应用密码（公开 master 历史）要由所有人登录 Bluesky 删除；当前 WiFi 屏蔽社交平台，之后再做。
  - 实测（2026-09-30）：`bsky.app`、`api.bsky.app`、`public.api.bsky.app` 被重置；`bsky.social` 可达，搜帖接口回 401（需登录）。已删除的旧代码（`7aa8b6b6^:marketmind/pipeline/social_sources.py`）只用 `bsky.social`，所以缺的只是凭据。
  - 恢复时：所有人新建应用密码，自己设用户环境变量 `BLUESKY_USERNAME` / `BLUESKY_APP_PASSWORD`（不贴进对话）；再从 git 历史取旧代码单独试跑（登录、按代码搜帖条数、内容价值），结果给所有人决定是否接回。不得使用泄露的旧密码。
- [ ] **警报推送开关 `MARKETMIND_ALERTS_LIVE`**：所有人 2026-09-30 决定暂不打开。截至当天账本中 `alert:*` 记录为 0；观察模式跑满 3–4 周且有若干条已结算警报后，在对话里提醒所有人决定。
- [ ] **360 安全卫士信任 MarketMind 计划任务**（2026-10-02）：`\MarketMind\` 下四个任务 10-02 00:40 左右被整体删除，时间与 360 清理模块运行吻合（未找到直接日志）。已重装。所有人需在 360 里把这些任务 / `pythonw.exe` 加入信任或关闭"开机加速"对它们的处理。排查漏跑时先跑 `Get-ScheduledTask -TaskPath '\MarketMind\'`。
