# 影子毕业考试与评估体系

**版本**: 1.0
**日期**: 2026-05-20
**状态**: 设计文档 — 待审批
**前置阅读**: `shadow-lifecycle-framework.md`、`shadow-type-redesign-v3.md`

---

## 1. 核心理念：从内部竞争到用户交互

影子不是选民，是独立基金经理。毕业不是"投票权"的授予，而是**"与用户对话的资格"**。毕业标准衡量影子作为独立决策者的综合投资能力，而非与群体的吻合度。

### 毕业的含义

```
未毕业影子:
  - 生态内部分析 → 仅用于排名、结晶、方法论进化
  - 对用户完全不可见

已毕业影子:
  - 保留生态内部分析职责
  - 获得 Gate 2 中被用户看到和召唤的权限
  - 每次 Gate 2 会话最多贡献一次，标记为"影子意见"，无决策权
  - 持续接受毕业后监控（CUSUM/CUSUMSQ/BOCPD）——表现下滑可被降级
```

### 毕业与成就阶梯的关系

成就阶梯是**生态内部**的相对排名（Elite/Excellent/Watch/Endangered），毕业是**绝对门槛**：

```
成就阶梯（内部）              毕业体系（外部）
─────────────              ─────────────
Elite       ←→ 可以毕业    Gate 2 资格    ←→ 用户交互
Excellent   ←→ 可以毕业    基础能力认证    ←→ 证明不是噪音
Watch       ←→ 不能毕业    类型专项卓越    ←→ 证明有 Alpha
Endangered  ←→ 不能毕业    毕业后监控      ←→ 持续有效
```

---

## 2. 毕业框架总览

```
新影子入职
    │
    ▼
观察期（Expert 90天 / Momentum 75天 / Contrarian 252天）
    │
    ▼
Tier 1: 基础能力认证（所有影子相同）
  - 胜率 ≥ 类型阈值  AND  收益率 > 0
  - Brier 分解：Eagle 或 Bull
  - 最低交易数达标  AND  最大回撤未触及上限
    │ 通过
    ▼
Tier 2: 类型专项卓越
  - Expert:   Sortino≥0.5, MAR≥0.8, GPR≥1.5, K-Ratio≥0.4
  - Momentum: Sortino≥0.3, MAR≥0.5, GPR≥1.2, K-Ratio≥0.3
  - Contrarian: Sortino≥0.25, MAR≥0.4, GPR≥1.0, K-Ratio≥0.25
  - Contrarian 特定基准: Fade Master→LT Rev+AAII极端模拟; Scout→LT Rev+区间模拟; Vol→CBOE PUT; Crash→CBOE SKEW+保护性看跌
  - 超越基准 + 超越主流水线（仅当主管道在影子领域有实际交易时对比）
    │ 通过
    ▼
压力测试: 2008 GFC / 2020Q1 COVID / 2022 加息冲击
    │ 通过
    ▼
Gate 2 资格激活 → 毕业后监控启动
```

---

## 3. Tier 1：基础能力认证

| 指标 | Expert | Momentum | Contrarian |
|------|:--:|:--:|:--:|
| **胜率** | ≥ 52% | ≥ 48% | ≥ 45% |
| **总收益率** | > 0% | > 0% | > 0% |
| **Brier Score 分解** | Eagle/Bull | Eagle/Bull | Eagle/Bull |
| **最低交易数** | ≥ 5 | ≥ 50 | ≥ 25-50 |
| **最大回撤** | < 25% | < 30% | < 35-40% |
| **Abstention 率** | ≤ 20% | ≤ 15% | ≤ 25% |

**Contrarian 最低交易数分层**: Fade Master 50, Sideways Scout 40, Vol Surfer 30, Crash Hunter 25。

**每日必决策原则**: 不确定时以 $100 最小仓位表达方向判断。thesis 注明 "MIN_POSITION:UNCERTAIN"。

**反博弈规则**: Tier 2 的年化收益率必须 > 无风险利率 + 2%（绝对值，非比率）。防止小额高胜率策略通过操纵低分母（波动率/回撤）来抬高 Sortino/MAR/GPR。

---

## 4. Tier 2：类型专项卓越

| 指标 | Expert | Momentum | Contrarian | 公式 |
|------|:--:|:--:|:--:|------|
| **Sortino** | ≥ 0.5 | ≥ 0.3 | ≥ 0.25 | (Rp-Rf)/DownsideDev |
| **MAR** | ≥ 0.8 | ≥ 0.5 | ≥ 0.4 | CAGR/|MaxDD| |
| **GPR** | ≥ 1.5 | ≥ 1.2 | ≥ 1.0 | Σ收益/Σ|亏损| |
| **K-Ratio** | ≥ 0.4 | ≥ 0.3 | ≥ 0.25 | Slope(VAMI)/SE(Slope) |
| **超越基准** | 领域ETF | SG Trend Index | Fama-French LT Rev |
| **跑赢主流水线** | 必须 | 必须 | 必须 |

**超越基准**: 配对 t 检验 α=0.10。基准数据: Ken French Data Library（完全免费）。**跑赢主流水线**: 影子领域内 Sortino > 主流水线同领域 Sortino。

---

## 5. 概率校准管道

```
原始置信度 → Venn-Abers 校准器 → Brier 三元分解 (MCB/DSC/UNC) → Manokhin 概率矩阵
```

### Brier 分解
BS = MCB + DSC - UNC（Dimitriadis "The Triptych", arXiv:2301.10803）

### Manokhin 概率矩阵

| 原型 | 校准 | 区分力 | 毕业资格 |
|------|:--:|:--:|:--:|
| **Eagle（鹰）** | ✓ 好 | ✓ 强 | ✅ 直接通过 |
| **Bull（牛）** | ✗ 差 | ✓ 强 | ✅ 后校准修复后通过 |
| **Sloth（树懒）** | ✓ 好 | ✗ 弱 | ❌ 需改进区分力 |
| **Mole（鼹鼠）** | ✗ 差 | ✗ 弱 | ❌ 需全面改进 |

**毕业要求**: 必须是 Eagle 或 Bull（经 Venn-Abers 校准后达到 Eagle 水平）。

---

## 6. 领域基准映射（16 Expert）

| # | 影子 | 主基准 | 辅助基准 |
|:--:|------|------|------|
| 1 | Bullion Broker | **GLD** | SLV, GDX |
| 2 | Chain Oracle | **BTC+ETH** 等权 | BITW |
| 3 | Oil Geologist | **XLE** | USO, UNG |
| 4 | Yield Whisperer | **AGG+TLT** 等权 | LQD |
| 5 | Vega Trader | **VIX Index + VXX** | VXZ |
| 6 | Frontier Scout | **EEM** | EMB, FXI |
| 7 | Silicon Oracle | **QQQ+SMH** 等权 | XLK |
| 8 | Bank Examiner | **XLF** | KRE |
| 9 | Trial Reviewer | **XLV+IBB** 等权 | PJP |
| 10 | Wallet Watcher | **XLY+XLP** 等权 | RTH |
| 11 | Factory Floor | **XLI** | ITA |
| 12 | Steel Trader | **DBB+CPER** 等权 | XME |
| 13 | Harvest Seer | **DBA** | CORN,WEAT,SOYB |
| 14 | REIT Analyst | **VNQ+IYR** 等权 | XLRE |
| 15 | Currency Dealer | **UUP+FXE** 等权 | FXY |
| 16 | Cycle Reader | **SPY/AGG/GLD** (60/30/10) | ACWI |

---

## 7. 毕业后三层监控

| 层级 | 方法 | 频率 | 触发动作 |
|------|------|:--:|------|
| Layer 1 | **CUSUM** on P&L | 每日 | 3月5次警报 → 重评估 |
| Layer 2 | **CUSUMSQ** on 残差 | 每日 | 触发 → **立即暂停 Gate 2** |
| Layer 3 | **Score-Driven BOCPD** | 每周 | L3+L1 联合 → 策略重优化 |

### 关键参考文献
- Hadjiliadis & Vecer (2006): CUSUM 回撤检测
- Brown, Durbin & Evans (1975): CUSUMSQ 方法论断裂
- Tsaknaki et al. (2025): Score-Driven BOCPD 体制检测

---

## 8. 压力测试

| # | 情景 | 回测区间 | Expert/Momentum | Contrarian 高频(Fade/Scout) | Contrarian 低频(Vol/Crash) |
|:--:|------|------|------|------|------|
| 1 | GFC | 2008-09 ~ 2009-03 | 回撤 ≤ 上限*1.5 | **必须正收益** | **条件正收益**（若历史回测显示激活条件触发 → 必须正收益；若激活条件未触发 → 免除收益要求） |
| 2 | COVID | 2020-02 ~ 2020-03 | 回撤 ≤ 上限*1.5 | **必须正收益** | **必须正收益** |
| 3 | 加息冲击 | 2022-01 ~ 2022-10 | 回撤 ≤ 上限 | 回撤 ≤ 上限 | 回撤 ≤ 上限 |

**低频 Contrarian 压力测试豁免**: 回测显示某影子在压力测试期间因激活条件未满足而休眠（0 交易）→ 免除正收益要求。休眠状态须经历史数据回测验证。

**Alpha 纯度**: Carhart 4因子（所有影子）+ Fung-Hsieh 7因子（Momentum/Contrarian）。α年化 > 0, t > 1.65。**风格漂移**: 月度因子暴露变化 ≤ 2σ。连续3月超标 → 降级。

---

## 9. 降级触发条件（8条）

| # | 条件 | 严重度 | 降级到 | 恢复条件 |
|:--:|------|:--:|:--:|------|
| D1 | CUSUMSQ 触发 | 严重 | SUSPENDED | 方法论修正+30天回测 |
| D2 | CUSUM 3月5次警报 | 高 | DISPLAY_ONLY | 20天无警报+α>0 |
| D3 | BOCPD+CUSUM 联合 | 高 | SUSPENDED | 新策略优于旧 |
| D4 | 降至 Endangered | 高 | SUSPENDED | Challenger 胜出 |
| D5 | 连续3周期 Watch | 中 | DISPLAY_ONLY | Tier 2 重检 |
| D6 | 风格漂移 3月>2σ | 中 | DISPLAY_ONLY | 方法论说明+回归 |
| D7 | 回撤触及上限 | 严重 | SUSPENDED | 全部流程重来 |
| D8 | 因子α<0 (t<-1.65) | 高 | DISPLAY_ONLY | α转正2月 |

### 9.1 降级优先级

当多个条件同时触发时，按以下优先级（高优先先执行，低优暂停）：
1. D7（回撤） > 2. D1（CUSUMSQ） > 3. D3（BOCPD+CUSUM） > 4. D4（Challenger胜出） > 5. D2（CUSUM） > 6. D8（因子α） > 7. D5（3x Watch） > 8. D6（风格漂移）

**竞态规则**: Challenger 对比试验进行中触发 D1/D3/D7 → 试验暂停，影子 SUSPENDED。解除后试验从暂停处继续（保留累积天数）。

### 9.2 成就阶梯（毕业前置条件）

成就阶梯基于**类型内百分位 + 连续天数**（权威定义）：

| 等级 | Expert | Momentum | Contrarian |
|------|:--:|:--:|:--:|
| **Elite** | 85%ile + 30天 | 85%ile + 20天 | 85%ile + 60天 |
| **Excellent** | 70%ile + 10天 | 70%ile + 7天 | 70%ile + 20天 |
| **Watch** | <30%ile + 10天 | <30%ile + 7天 | <30%ile + 30天 |
| **Endangered** | <15%ile + 20天 | <15%ile + 14天 | <15%ile + 40天 |

**前置条件**: 影子必须先达到 Elite 或 Excellent 才能参加毕业考试。**不是自动毕业**: 等级达标 ≠ 毕业。毕业 = Tier 1 + Tier 2 + 压力测试全部通过。毕业后降至 Excellent 以下 → 自动暂停 Gate 2 权限。

**无任期原则**: 对标 Millennium/Citadel——即使 Elite 300 天，今天触发 D1 今天暂停。

---

## 10. 实施路线图

| Phase | 内容 | 预估工作量 |
|------|------|:--:|
| G1 | 校准基础设施: venn_abers.py + brier_decomposition.py + manokhin_matrix.py | ~450行纯Python |
| G2 | 毕业评估引擎: graduation_engine.py | ~300行 |
| G3 | 毕业后监控: post_graduation_monitor.py (CUSUM+CUSUMSQ+BOCPD) | ~400行 |
| G4 | 因子分析: factor_analyzer.py (Carhart 4F + Fung-Hsieh 7F) | ~300行 |
| G5 | Gate 2 集成 + UI | ~200行 |
| G6 | PICA 审计 | 4个审计产物 |

---

## 参考文献

| 文献 | 用途 |
|------|------|
| Jegadeesh & Titman (1993) | 动量策略胜率阈值 |
| DeBondt & Thaler (1985) | 逆向策略理论基础 |
| Dimitriadis et al. (2023) — "The Triptych" | Brier 三元分解 |
| Manokhin (2026) — "Probability Matrix" | Eagle/Bull/Sloth/Mole 分类 |
| Hadjiliadis & Vecer (2006) | CUSUM Alpha 衰减检测 |
| Brown, Durbin & Evans (1975) | CUSUMSQ 方法论断裂 |
| Tsaknaki et al. (2025) | Score-Driven BOCPD 体制检测 |
| Carhart (1997) | 四因子模型 |
| Fung & Hsieh (2004) | 七因子模型 |
| Vovk et al. (2005, 2015) | Venn-Abers 预测器 |
