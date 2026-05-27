# MarketMind Restart Guide — 2026-05-27 EOD

**Tests**: all passing | **CI**: green | **Branch**: master
**All pushed**: yes | **frontload_required**: false

---

## 重启指令

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。
> 上次完成：全量 UI 重设计 + 僵尸检测 + 信息流验证 + 实盘全量跑通。
> **下次主要任务**：人工审核主管线 AI 迭代进化体系是否合理 + 调试 UI 界面和交互逻辑。

---

## 快速命令

```bash
cd E:/AI_Studio_Workspace/projects/marketmind

# 启动 Dashboard
python api_server.py
# → http://localhost:8520/
# → http://localhost:8520/playground
# → http://localhost:8520/evolution

# Mock 管线 (无 API 消耗, ~1min)
python app.py --mode daily --mock -v

# Mock 管线 + Playground agents
python app.py --mode daily --mock --playground -v

# 实盘管线 (~7min, 消耗 API)
python app.py --mode daily --playground -v

# 交互模式 (Socratic 对话 + 决策确认)
python app.py --mode interactive -v

# 测试
python -m pytest tests/ -q -p no:warnings
```

---

## 今日完成 (2026-05-27)

### Playground 实验层
- `playground/` 7 模块：agent 自声明、WP API+RSS 双通道、信息防火墙、次日结算、升级门控、月度审计
- serenity-reply 首个入驻：两轮 Flash 分析 + 研究循环 + 审计日志
- 8 CORE 半导体源 (6 WP API + 2 RSS)，1 SUPPLEMENTAL，6 RETIRED
- 4 源合入主 Scout (EE Times, Semiconductor Engineering, EDN, EE Times Asia)
- Playground 日报：`playground/data/daily/YYYY-MM-DD.md`
- Dashboard: `/playground` 卡片式 UI，状态驱动配色

### 主管线三层进化体系
- Layer 1: `daily_calibration.py` 增强 (Flash 验证率 + HVR ROI)
- Layer 2: `pipeline_metrics.py` 日记录 + `weekly_tactical_audit.py` 周审计
- Layer 3: `methodology_evolution.py` 跨阶段归因 (准确率 <45% 触发)
- 全部接入 orchestrator：指标记录 → 周审计 → 归因 → L1 prompt 注入

### Dashboard UI 重设计
- 主管道结论面板：点击展开完整推理链 (L1/L2/L3/Red Team/Resonance/Decision)
- 影子生态：24 影子 (16 Experts + 8 Daredevils)，中英双语 methodology
- Tier 分布面板替代跨域排名 (不同波动率体质的影子不可直接比序数)
- Catfish 影子退役 (被 `ecosystem_auditor.py` 机制取代)
- 僵尸检测：`zombie_detector.py` 每次启动自动对比代码 vs DB

### Bug 修复
- Playground gateway event loop 冲突 (新 loop 中 re-init)
- `pipeline_metrics` FlashSignal 类型兼容
- 影子 VOTE→DECISION 重命名遗漏 (`get_votes_by_date_range`, `wfe_results`)
- 影子 LLM float 解析 (`_safe_float` 处理 `EST:0.35` 等噪声)

### 实盘验证
- 全链路跑通：37 主 Scout 源 → Flash 18 信号 → L1 grade=A → L3 0 green → no-trade
- serenity-reply 成功调用 Flash 产出 1388 字符分析
- Playground 日报和市场简报正常生成

---

## 当前架构快照

```
主管线: Scout(37源) → Flash → L1 → L2+L3 → Shadows → RedTeam → Resonance → Decision
         ↑                                    ↑
   每日校准 + 周审计建议注入            非阻塞后台启动
         ↑                                    ↑
   pipeline_metrics 记录               zombie_detector 启动检查

Playground: WP API(6) + RSS(2) → serenity-reply adapter → Flash 两轮分析
              ↓                                    ↓
        信息防火墙 (无主管道数据)            research_log 审计

影子生态: 24 shadows (16 Experts + 8 Daredevils)
         Tier: ELITE/EXCELLENT/NORMAL/ENDANGERED
         淘汰: 3 阶段管道 (警告→挑战者→21天配对检验)
```

---

## 给下次开发

1. **人工审核主管线进化体系**：检查 `daily_calibration.py` + `weekly_tactical_audit.py` + `methodology_evolution.py` 的 Layer 3 跨阶段归因是否合理
2. **UI 调试**：Dashboard 面板、影子卡片、Playground 页面的交互逻辑
3. **等数据积累**：多跑几天管线让 metrics/排名/Tier 有真实数据
4. **Playground 入驻指南**：新 agent 在 `playground/agents/` 下新建目录 + manifest.json + adapter.py
