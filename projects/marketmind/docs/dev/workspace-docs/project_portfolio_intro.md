# MarketMind — AI-Powered Investment Decision Platform / AI 驱动的投资决策平台

> 个人项目 | 独立主导 | 2025-2026 | AI PM 作品集
> Solo Project | Independent PM + Development | 2025-2026

---

## 项目概览 / Elevator Pitch

MarketMind 是一个基于多智能体协作的 AI 投资决策辅助系统。它运行 22+ 个独立 AI"影子分析师"，每个影子拥有不同的专业领域和投资哲学，通过对同一市场数据并行分析、竞争排名、交叉验证，最终汇聚为人类投资者的决策参考。项目完成 565 个自动化测试，零生产回归。

MarketMind is a multi-agent AI investment decision support system. It runs 22+ independent AI "shadow analysts," each with different expertise and investment philosophy. They analyze the same market data in parallel, compete on composite performance scores, cross-validate each other's signals, and collectively inform human investment decisions. 565 automated tests pass with zero regressions.

**角色 / Role**: AI 产品经理（独立主导） / AI Product Manager (Solo Lead)
**技术栈 / Stack**: Python, LLM (DeepSeek Flash/Pro), SQLite, asyncio, customtkinter
**周期 / Timeline**: 2026 年 5 月至今，持续迭代开发

---

## 1. 产品架构 / Product Architecture

### 1.1 双轨决策管线 / Dual-Track Decision Pipeline

```
市场数据 → 主 AI 决策管线 (L1 叙事 / L2 基本面 / L3 技术面)
         → 22 影子并行分析 → 排名引擎 → 共识/分歧检测
                                  ↓
                         汇聚为最终投资决策
```

主 AI 负责三层递进分析，Red Team 对抗性审查每个结论，信号共振验证统计学显著性。影子生态通过竞争排名机制独立验证同一信号，避免单一模型偏差。

### 1.2 影子生态系统 / Shadow Ecosystem

22 个独立 AI 影子分为 7 种类型，设计借鉴对冲基金多策略管理模式：

| 类型 | 数量 | 设计目的 |
|------|------|---------|
| 专家型 Expert | 15 | 黄金、加密、能源、债券、波动率、新兴、科技、金融、医疗、消费、工业、金属、地产、外汇、宏观 |
| 冒险型 Daredevil | 5 | 趋势跟踪、逆势交易、事件驱动、板块轮动、波动率套利 |
| 鲶鱼型 Catfish | 1 | 共识 >=80% 时强制执行少数派观点，防止群体思维 |
| 挑战者型 Challenger | 动态 | 3 阶段淘汰制——警告→秘密影子创建→双盲对比试验 |
| 临时事件型 Temp | 动态 | 央行冲击、地缘危机触发，Form C 里程碑式记录，30 天生命周期 |
| 错失路径型 MissedPath | 动态 | Gate 1 被拒方向的反事实追踪，防幸存者偏差 |
| 实验型 Beta | 可配置 | AEL 受控实验对照组 |

### 1.3 排名与淘汰机制 / Ranking & Elimination

- **复合评分**: MPPM (Goetzmann) / Calmar (年化收益/最大回撤) / Omega / WinRate 四项加权
- **Bayesian 过拟合惩罚**: Witzany 公式 + Effective-N 修正（N / (1 + (N-1) × mean_abs_corr)）
- **Walk-Forward 验证**: 90 天训练 / 2 天净化 / 20 天测试滑动窗口，WFE < 0.5 判定过拟合
- **Holm-Bonferroni 校正**: 22 个影子多重比较，family-wise error rate 控制在 5%
- **动态胜率线**: 初期 55% 鼓励方向准确 → 成熟期 45% 允许以盈亏比换取低胜率
- **负收益惩罚**: 最大惩罚因子 40%，直接触及 tier 降级

---

## 2. LLM 应用设计 / LLM Engineering

### 2.1 模型路由 / Model Routing

| 模型 | 用途 | 频次 |
|------|------|------|
| DeepSeek Flash | 数据收集、简单分类、预处理、单行评论 | 高频 (100/天) |
| DeepSeek Pro | 深度分析、对抗推理、影子分析、最终报告 | 低频 (30/天) |

所有调用通过统一异步网关，含 TokenBudget 预算控制 + API Key 轮转 + 共享配额池检测。

### 2.2 Prompt 工程 / Prompt Engineering

- **M1 数据完整性协议**: 所有数值声明必须引用可验证来源，"EST:" 标注估计值，"DATA_UNAVAILABLE" 标记缺失——防止 LLM 虚构金融数据
- **Cash Reframing 协议**: 用"如果你今天持有现金，会买入吗？"替代持仓锚定偏差（Kahneman 禀赋效应）
- **SHARP 规则治理**: 静态 DECISION_SYSTEM_PROMPT 分解为 60+ 可审计 MainAIRule，支持动态组装、A/B 验证、Walk-Forward 回测门控自动退役

### 2.3 可靠性与容错 / Reliability Engineering

- **Circuit Breaker**: CLOSED→OPEN→HALF_OPEN 状态机，429 用 Retry-After，5xx 用 30s，配额耗尽特殊处理
- **Fallback Provider**: 独立 API Key（不泄露主 Key），可配置 URL + Model
- **断点续跑**: Per-shadow checkpoint + resume 检测，崩溃后跳过已完成分析
- **信号质量追踪**: Triple-Barrier 标注（止损/止盈/时间到期），纯诊断指标

---

## 3. 质量保障体系 / Quality Assurance

### 3.1 统计严谨性 / Statistical Rigor

- **Walk-Forward 验证**: 打破 IS 过拟合幻觉，OOS/IS < 0.5 直接惩罚排名分数
- **外部市场锚点**: 影子方向准确率 vs 实际市场回报，< 50% 不准晋升 ELITE
- **对照实验框架**: Treatment/Control A/B，Wilcoxon signed-rank 检验，alpha=0.10
- **Effective-N**: 相关性矩阵修正下的有效影子数量，防止虚假多样性

### 3.2 Red Team 审计流程 / Red Team Audit

所有优化方案必须通过三红方独立审核（逻辑设计 + 安全 + 数据兼容性），每个给出: 批准 / 有条件批准 / 驳回。本次 Phase B 回审中：
- 发现 15 个问题（2 紧急 / 5 高优 / 4 中优 / 4 低优）
- 4 项外部研究方案提交红方，1 项被驳回，3 项有条件批准
- 最终 565 测试全过，零回归

### 3.3 自动化测试 / Test Coverage

565 个自动化测试覆盖全模块（单元 + 集成 + E2E），运行时间约 60 秒。每项修复后立即运行相关测试，全量测试确认零回归。

---

## 4. 产品管理方法论 / PM Methodology

### 4.1 自创 6 阶段 Phase 审计工作流

```
Phase 0: 状态恢复 + 断点检测
Phase 1: Grill Me（brainstorming 深度挖掘需求 + 回顾既有 Red Team 审计）
Phase 2: 三方并行审查（代码质量 / 安全架构 / 外网研究）
Phase 3: 合并发现 → 按严重度排序 → 写优化方案
Phase 4: 三红方并行审核（逻辑 / 安全 / 数据兼容）→ 批准/驳回
Phase 5: 基线测试 → 逐项修复 → 全量验证（零回归 bar）
Phase 6: 断点标记 → commit → 路线图更新
```

核心理念：**没有外部独立的 Red Team 审核，永远不能宣布完成。**

### 4.2 关键设计决策 / Key Design Decisions

| 决策 | 理由 |
|------|------|
| 所有影子默认 Pro 模型 | 分析质量优于成本（Pro 单次成本 $0.01-0.05） |
| 挑战者继承 ORIGINAL 方法论 | 避免 AEL 进化偏差在代际间放大 |
| 价格数据仅为时序过滤器 | 反过拟合（Law 3），不直接作为信号源 |
| 空仓视为有效决策 | 不强制交易，机会成本优于亏损 |
| 每次 sub-phase 完成后 commit | 版本控制粒度，可追溯每项变更 |
| Challenger 数据对目标影子不可见 | 双盲设计，防止双方策略互适应 |

---

## 5. 适用岗位建议 / Role Targeting

### 🇨🇳 中国 AI PM 岗位

**重点突出**:
- 多智能体系统架构设计与产品化落地
- LLM Prompt 工程方法论（完整性协议 + 偏差消除）
- A/B 测试框架设计与统计学验证
- Red Team 质量门控流程
- 565 测试套件的质量工程实践

### 🇺🇸 US AI PM Roles

**Highlight**:
- Multi-agent system architecture (22+ independent AI agents)
- LLM reliability engineering (circuit breaker, fallback routing, token budget)
- Statistical rigor in product validation (walk-forward, Holm-Bonferroni, Effective-N)
- Red Team audit governance process
- End-to-end product ownership from architecture to 565-test QA suite

### 通用 PM 岗位

**突出**: 复杂系统产品架构、跨模块集成管理、质量门控流程设计、设计决策文档化、项目管理方法论创新

---

## 6. 数据一览 / By The Numbers

| 指标 | 数值 |
|------|------|
| AI 影子数量 | 22+ (7 种类型) |
| 代码模块 | 50+ Python 文件 |
| SQLite 表 | 15 张 |
| Schema 迁移 | 5 次零事故 |
| 自动化测试 | 565 个 |
| 测试运行时间 | ~60 秒 |
| 回审发现问题 | 15 个（已全部修复） |
| Red Team 审核轮次 | 4 轮 |
| 外部研究参考 | Lopez de Prado, Spotify Fixed-Power, AAR, ILPA, Kohavi et al. |
| LLM 日调用上限 | Flash 100 / Pro 30 |
| 日 Token 预算 | 2,000,000 |
