# MarketMind Restart Guide — 2026-05-30 EOD

**Tests**: 27/27 relevant tests pass | **CI**: green | **Branch**: master
**All pushed**: no | **frontload_required**: false

---

## 重启指令

> 继续 MarketMind 开发。读 projects/marketmind/.claude/RESTART_GUIDE.md。
> 上次完成：全 UI 大修（9 语种选择器 + 决策卡片中文化 + Paper Trade 虚拟投资 + 进度条阶段追踪+卡死检测 + 管道进度 WebSocket 上报 + 按钮默认实盘+MOCK + 卡片展开状态保持 + 决策模块 9 语种 i18n `_t()` 字典 + AI prompt 语言注入 `_lang_instruction()`）。

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

## 今日完成 (2026-05-30)

### 语言选择器 + AI 语言注入
- `dashboard.html`：9 语种下拉（zh/en/es/fr/ru/ar/ja/ko/de），`t()` 函数多语言 UI
- `app.py`：`--lang` 参数，设置 `MARKETMIND_LANG` 环境变量
- `api/routes.py`：接受 `lang` 参数传递 `--lang` 给子进程
- `pipeline/decision.py`：`_lang_instruction()` 注入 system prompt，`_I18N` 字典 + `_t()` 函数覆盖全部 9 语种的 fallback 消息和 PaperTrade 标签

### 进度条增强
- `pipeline/stage_tracker.py`：`_report_stage_progress()` — 每阶段 HTTP POST 到 API 服务器
- `api/websocket.py`：`broadcast_stage()` 支持 `stage_num`
- `dashboard.html`：显示 "3/9 StageName" + 每阶段耗时 + 颜色变化 + STUCK 检测

### 决策卡片重设计
- 中文标签（宏观叙事/技术灯/对抗挑战/统计验证），点击展开/收起
- **展开状态保持**：5 秒刷新周期不再冲掉展开状态（`window._decExpanded` 标志位）
- 颜色编码 🟢绿灯 🟡黄灯 🔴红灯

### 虚拟投资 Paper Trade
- `pipeline/decision.py`：`PaperTrade` 数据类 + `_pick_paper_trade()` — 当 no_trade 时自动选最有把握方向
- `pipeline/orchestration.py`：`_save_decision_brief` 存储 `paper_trade`
- UI：虚线卡片 "📝 虚拟投资" + 标的/方向/置信度/逻辑

### 按钮 + 管道修复
- 默认实盘（`mock=false`），MOCK 按钮独立
- 管道进度 HTTP POST → API → WebSocket → 前端进度条
- `stdout=subprocess.DEVNULL` 修复 pipe buffer 死锁
- 管线完成后按钮一直闪烁不恢复 — WebSocket `done`/`error` 中加入按钮重置

---

## 当前架构快照

```
主管线: Scout(37源) → Flash → HVR → L1 → L2+L3 → Shadows → RedTeam → Resonance → Decision
         │                        │                    │
    每日校准 + 周审计        进度 HTTP POST       24 影子(非阻塞后台)
         │                        │                    │
    Calibration             api_server:8520      ShadowMother
    (含进化通知)          WebSocket→Dashboard     (排名/串谋/挑战者)
```

---

## 已知问题

| 问题 | 严重度 | 说明 |
|:--|:--|:--|
| 聊天框未接通 AI | 中 | `sendMsg()` 无后端 API，需要 `/api/chat` 端点 |
| 其他模块未注入语言指令 | 低 | L1/L2/L3/RedTeam 的 prompt 还没读 `MARKETMIND_LANG`，只有 decision 模块已注入 |
| 虚拟投资端到端未实际验证 | 低 | `_pick_paper_trade` 逻辑已写好，需跑管线验证 |
| 网络/代理不稳定 | 低 | 部分 fetcher 测试在网络差时失败 |

---

## 待办 (优先级排序)

1. **聊天框接通 AI** — 添加 `/api/chat` 端点，让管道分析和用户对话通过聊天框进行
2. **其他模块语言注入** — L1/L2/L3/RedTeam/Resonance 的 prompt 也读取 `MARKETMIND_LANG`
3. **端到端测试** — `--lang zh` 跑一条 mock 管线，验证全链路中文输出
4. **数据积累** — 多跑几天管线让影子排名有真实数据

---

## 流程优化 (HARD GATE #5)

### 方法论优化
1. **子进程进度上报模式**：HTTP POST + WebSocket 广播，适用于任何后台子进程向 Dashboard 报告进度
2. **pipe buffer 死锁规则**：fire-and-forget 子进程必须用 `DEVNULL`，禁止 `PIPE`
3. **5 秒轮询 UI 状态保持**：轮询刷新重建 DOM 时需保存/恢复交互状态（如 `window._decExpanded`）

### 根规则更新
- 建议：所有 `subprocess.Popen` 非交互调用必须指定 `stdout=DEVNULL, stderr=DEVNULL`

### 流程瓶颈
- 无：本次改动从诊断到实现到测试无返工

---

## 关键文件清单

| 文件 | 用途 |
|------|------|
| `dashboard.html` | Dashboard 前端（语言选择器、进度条、决策卡片、聊天） |
| `api/routes.py` | API 路由 |
| `api/websocket.py` | WebSocket 管理 |
| `app.py` | CLI 入口（--lang, --mock） |
| `pipeline/stage_tracker.py` | 阶段追踪 + HTTP 进度上报 |
| `pipeline/orchestration.py` | 管线编排 |
| `pipeline/decision.py` | 决策生成 + PaperTrade + 语言注入 |
| `shadows/shadow_mother.py` | 影子生态总指挥 |
| `shadows/shadow_state.py` | 影子 SQLite 持久化 |
