# MarketMind Restart Guide — 2026-05-31 EOD

**Tests**: 2,159/2,159 pass (1 flaky network test excluded) | **CI**: green | **Branch**: master
**All pushed**: no | **frontload_required**: false

---

## 重启指令

> 继续 MarketMind 开发。读 projects/marketmind/.claude/RESTART_GUIDE.md。
> 上次完成：聊天体验优化（loading 动画 + Retry 重试 + Markdown 渲染）+ 影子生态机制审查。

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
- `api/chat_handler.py`：ChatManager + ChatSession 会话管理，chat_pro() 调用
- `api/routes.py`：POST /api/chat, GET/DELETE /api/chat/history
- `dashboard.html`：sendMsg() 文本→AI 对话，文件→管线注入

### 2. 全模块语言注入
- `pipeline/language_utils.py`：共享 lang_instruction() + lang_note()
- L1/L2/L3/RedTeam/L2-Interactive：全部读取 MARKETMIND_LANG
- Resonance + FragilityScanner：无 LLM 调用，跳过

### 3. 聊天体验优化
- **Loading 动画**：AI 思考时显示脉冲 "● ● ●" 占位消息
- **Retry 重试**：失败消息旁显示 Retry 链接，点击重新发送
- **Markdown 渲染**：AI 回复支持 **bold**, *italic*, `code`, ```block```, ### headers, - lists, [links](url), > blockquote, --- hr
- **用户前缀修正**：`▶ 用户:` 前缀直接显示

### 4. 影子生态机制审查
- 临时影子 4 类：temp_event（事件记录器 30d）、missed_path（反事实追踪）、challenger（秘密挑战者）、beta（领域播种）
- 影子生命周期：Birth → Analysis → Ranking → Crystallization → Challenger → Cleanup
- ShadowMother 13 步 daily cycle 编排

### 测试
- Pipeline: 1,043 passed | API: 45 passed | Full: 2,159 passed（1 flaky network）

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

聊天 UX:
  ✅ Loading 动画   ✅ Retry 重试         ✅ Markdown 渲染
```

---

## 已知问题

| 问题 | 严重度 | 说明 |
|:--|:--|:--|
| L2 prompt 内嵌中文格式要求 | 低 | 非中文语言下 lang_note() 末尾覆盖可能产生混合语言输出 |
| 虚拟投资端到端未实际验证 | 低 | `_pick_paper_trade` 逻辑已写好，需跑真实管线验证 |
| 网络/代理不稳定 | 低 | test_fetch_core_sources 在网络差时失败 |
| Markdown render 简单实现 | 低 | 基础正则渲染，不支持嵌套格式、表格、图片 |

---

## 待办 (优先级排序)

1. **主管线迭代流程审查** — 用户要求审查 Stage 间过渡、Gate 逻辑、管道是否有卡死点
2. **临时影子处理策略** — 审查 temp_event/missed_path/challenger/beta 的清理和资源管理
3. **L2 深层语言化** — LAYER2_SECTOR_DRILLDOWN_PROMPT 中的硬编码中文格式改为语言感知
4. **数据积累** — 多跑几天管线让影子排名有真实数据

---

## 流程优化 (HARD GATE #5)

### 方法论优化
1. **影子生态分层架构**：永久影子（expert/daredevil/momentum/contrarian）→ 临时影子（temp_event/missed_path/challenger/beta）→ 维护系统（breeding/evolution/crystallization），三层清晰分离
2. **前端渐进增强模式**：loading → retry → Markdown，每一步独立可测试，不互相依赖

### 根规则更新
- 无需更新

### Agent 配置
- Explore Agent × 1：深度扫描 shadows/ 目录 70+ 文件，15 分钟完成完整生态映射

### 流程瓶颈
- 无：三阶段任务均一次性完成

---

## 关键文件清单

| 文件 | 用途 |
|------|------|
| `dashboard.html` | Dashboard 前端（语言选择器、进度条、决策卡片、聊天+Markdown） |
| `api/routes.py` | API 路由（含 /api/chat 等 3 端点） |
| `api/chat_handler.py` | 聊天会话管理 + AI 调用 |
| `api/websocket.py` | WebSocket 管理 |
| `api/data_providers.py` | API 数据提供层 |
| `app.py` | CLI 入口（--lang, --mock） |
| `pipeline/language_utils.py` | 共享语言指令辅助 |
| `pipeline/layer1_narrative.py` | L1 叙事分析 + 语言注入 |
| `pipeline/layer2_fundamental.py` | L2 基本面分析 + 语言注入 |
| `pipeline/layer3_technical.py` | L3 技术面分析 + 语言注入 |
| `pipeline/red_team.py` | 红队审计 + 语言注入 |
| `pipeline/l2_interactive.py` | L2 交互式流程 + 语言注入 |
| `pipeline/decision.py` | 决策生成 + PaperTrade + 语言注入 |
| `pipeline/stage_tracker.py` | 阶段追踪 + HTTP 进度上报 |
| `pipeline/orchestration.py` | 管线编排 |
| `gateway/async_client.py` | DeepSeek API 网关 |
| `shadows/shadow_mother.py` | 影子生态总指挥（13-step daily cycle） |
| `shadows/shadow_state.py` | 影子 SQLite 持久化 |
| `shadows/temp_shadow_lifecycle.py` | 临时影子生命周期管理 |
| `shadows/challenger_engine.py` | 挑战者 3 阶段淘汰管线 |
| `tests/test_api/test_chat_handler.py` | 聊天模块测试 |
