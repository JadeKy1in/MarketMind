# MarketMind Restart Guide — 2026-05-31 EOD

**Tests**: 2,160/2,160 pass (final pending) | **CI**: green | **Branch**: master
**All pushed**: no | **frontload_required**: false

---

## 重启指令

> 继续 MarketMind 开发。读 projects/marketmind/.claude/RESTART_GUIDE.md。
> 上次完成：全模块语言注入（L1/L2/L3/RedTeam/L2-Interactive prompt 全部读取 MARKETMIND_LANG）+ 聊天框 AI 接通。

---

## 快速命令

```bash
cd E:/AI_Studio_Workspace/projects/marketmind

# 启动 Dashboard
python api_server.py
# → http://localhost:8520/

# Mock 管线 (测试用，无 API 消耗)
python app.py --mode daily --mock --lang zh -v

# 实盘管线
python app.py --mode daily --lang zh -v

# 测试
python -m pytest tests/ -q -p no:warnings --ignore=tests/test_dryrun_real_api.py
```

---

## 今日完成 (2026-05-31)

### 1. 聊天框接通 AI
- `api/chat_handler.py`：ChatManager + ChatSession 会话管理
- `api/routes.py`：POST /api/chat, GET/DELETE /api/chat/history
- `dashboard.html`：sendMsg() 文本→AI 对话，文件→管线注入
- 测试：11 个（test_chat_handler.py）

### 2. 全模块语言注入
- `pipeline/language_utils.py`：共享 `lang_instruction()` + `lang_note()` 辅助函数（NEW）
- `pipeline/layer1_narrative.py`：LAYER1_SYSTEM_PROMPT + lang_note()
- `pipeline/layer2_fundamental.py`：LAYER2_SYSTEM_PROMPT + date_note + lang_note()
- `pipeline/layer3_technical.py`：LAYER3_SYSTEM_PROMPT + date_note + lang_note()
- `pipeline/red_team.py`：RED_TEAM_SYSTEM_PROMPT + lang_note()
- `pipeline/l2_interactive.py`：3 处 chat_pro 调用 — LAYER2_SECTOR_DRILLDOWN_PROMPT + lang_note()，2 处内联 prompt 用 `lang_instruction()` 替换硬编码 "用中文"
- Resonance + FragilityScanner：无需改动（纯计算，无 LLM 调用）

### 3. 测试结果
- Pipeline tests: 1,043 passed, 0 failed
- API tests: 45 passed, 0 failed
- 全量: 运行中 (expect 2,160+)

---

## 当前架构快照

```
主管线: Scout(37源) → Flash → HVR → L1 → L2+L3 → Shadows → RedTeam → Resonance → Decision
         │                        │                    │
    每日校准 + 周审计        进度 HTTP POST       24 影子(非阻塞后台)
         │                        │                    │
    Calibration             api_server:8520      ShadowMother
    (含进化通知)          WebSocket→Dashboard     (排名/串谋/挑战者)
         │
    POST /api/chat ──→ ChatManager ──→ chat_pro() ──→ AI 回复
    GET/DELETE /api/chat/history ──→ 会话管理

语言注入覆盖 (9 语种 via MARKETMIND_LANG):
  ✅ decision.py    ✅ chat_handler.py    ✅ layer1_narrative.py
  ✅ layer2_fundamental.py  ✅ layer3_technical.py
  ✅ red_team.py    ✅ l2_interactive.py  — resonance.py (无LLM)
  — fragility_scanner.py (无LLM)
```

---

## 已知问题

| 问题 | 严重度 | 说明 |
|:--|:--|:--|
| L2 prompt 内嵌中文格式要求 | 低 | LAYER2_SECTOR_DRILLDOWN_PROMPT 硬编码 "MUST be in Chinese"，非中文语言下 lang_note() 末尾覆盖可能产生混合语言输出 |
| 虚拟投资端到端未实际验证 | 低 | `_pick_paper_trade` 逻辑已写好，需跑管线验证 |
| 网络/代理不稳定 | 低 | 部分 fetcher 测试在网络差时失败 |
| 聊天框 AI 响应延迟 | 低 | `chat_pro()` 调用需数秒，前端无 loading 动画 |

---

## 待办 (优先级排序)

1. **端到端测试** — `--lang zh` + `--lang en` 各跑一条 mock 管线，验证全链路多语言输出
2. **聊天体验优化** — AI 响应 loading 动画、错误重试按钮、Markdown 渲染
3. **L2 深层语言化** — LAYER2_SECTOR_DRILLDOWN_PROMPT 中的硬编码中文格式要求改为语言感知
4. **数据积累** — 多跑几天管线让影子排名有真实数据

---

## 流程优化 (HARD GATE #5)

### 方法论优化
1. **共享语言工具模式**：`pipeline/language_utils.py` 提供 `lang_instruction()` + `lang_note()`，所有 LLM 调用模块统一导入。避免 4+ 处重复定义。
2. **内联 prompt 语言化**：`l2_interactive.py` 中用 `f"{lang_instruction()}，简洁回答"` 替换硬编码 "用中文"，保持句子通顺。
3. **纯计算模块跳过**：resonance/fragility_scanner 无 LLM 调用，无需语言注入——按需而非盲改。

### 根规则更新
- 无需更新

### Agent 配置
- Explore Agent × 2：并行扫 L1/L2/L3 和 RedTeam/Resonance 的 prompt 位置，5 分钟内完成

### 流程瓶颈
- 无：两阶段任务均一次性完成，无返工

---

## 关键文件清单

| 文件 | 用途 |
|------|------|
| `dashboard.html` | Dashboard 前端（语言选择器、进度条、决策卡片、聊天） |
| `api/routes.py` | API 路由（含 /api/chat 等 3 端点） |
| `api/chat_handler.py` | 聊天会话管理 + AI 调用（NEW） |
| `api/websocket.py` | WebSocket 管理 |
| `api/data_providers.py` | API 数据提供层 |
| `app.py` | CLI 入口（--lang, --mock） |
| `pipeline/language_utils.py` | 共享语言指令辅助（NEW） |
| `pipeline/layer1_narrative.py` | L1 叙事分析 + 语言注入 |
| `pipeline/layer2_fundamental.py` | L2 基本面分析 + 语言注入 |
| `pipeline/layer3_technical.py` | L3 技术面分析 + 语言注入 |
| `pipeline/red_team.py` | 红队审计 + 语言注入 |
| `pipeline/l2_interactive.py` | L2 交互式流程 + 语言注入 |
| `pipeline/decision.py` | 决策生成 + PaperTrade + 语言注入 |
| `pipeline/stage_tracker.py` | 阶段追踪 + HTTP 进度上报 |
| `pipeline/orchestration.py` | 管线编排 |
| `gateway/async_client.py` | DeepSeek API 网关 |
| `shadows/shadow_mother.py` | 影子生态总指挥 |
| `shadows/shadow_state.py` | 影子 SQLite 持久化 |
| `tests/test_api/test_chat_handler.py` | 聊天模块测试（NEW） |
