# MarketMind 外部迭代机制调研 — 2026-05-31

**来源**: 3 轮网络搜索，覆盖 LLM 自优化 / 金融交易 AI / 多 Agent 协调 / 自动 Prompt 优化 / 市场制度检测 5 个方向

---

## 一、当前 MarketMind 已具备的机制

| 机制 | 分类 | 状态 |
|------|------|:--:|
| 7天方向精度校准 + 注入 L1 prompt | 日校准 | ✅ |
| 量级加权分数 (correct on small, wrong on large) | 日校准 | ✅ |
| 周战术审计 (Flash 分析 Stage 健康度) | 周审计 | ✅ |
| SHARP 规则进化 (LLM 假设 + walk-forward gate 判断) | 按需进化 | ✅ |
| L1 早停 (grade=E → 跳过后续 Stage) | 跨 Stage 实时 | ✅ |
| L2-L3 交叉检测 (标的全部红灯 → WARN) | 跨 Stage 实时 | ✅ |
| Red Team → Resonance PBO 收紧 | 跨 Stage 实时 | ✅ |
| Fragility → Decision 风险警告 | 跨 Stage 实时 | ✅ |
| 事后反思 (ReflectionAgent) + 实体记忆 | Phase I 学习 | ✅ |
| Platt Scaling 置信度校准 | Phase I 学习 | ✅ |
| Brier/ECE 校准追踪 | Phase I 学习 | ✅ |
| Decision 独立 contrarian 挑战 | 对抗验证 | ✅ |

---

## 二、最值得引入的 6 个外部机制

### 机制 1: 自适应信号抑制门 (Adaptive Suppression Gate)

**来源**: ROT (Reddit Options Trader) 9-Stage Pipeline + NVIDIA MAPE Data Flywheel

**问题**: 当前 MarketMind 的 Flash 阶段产生 A-E 级信号后，所有信号进入 L1/L2/L3 处理。即使某些类型的信号历史上从未产生过有效交易，仍然消耗 Pro 调用。

**方案**:
```
Flash → [Adaptive Suppression Gate] → L1
          │
          检查: 该信号类型的历史 ROI (信号 → 有效决策 的转化率)
          如果 ROI < 阈值 (连续 N 天为 0) → suppress
          保存 Pro 调用，信号记录到 "抑制日志" 供审计
```

**MarketMind 适配**:
- 在 Stage 2 (Flash) 和 Stage 3 (L1) 之间插入
- 跟踪每个 `event_type × event_grade` 组合的历史转化率
- 转化率 = (产生 decision_card 的天数) / (出现天数)
- 如果连续 5 天转化为 0 → suppress
- 每周重置：市场条件变化后重新评估

**预期收益**: 减少无效 L1 Pro 调用 ~15-30%

---

### 机制 2: 制度感知校准 (Regime-Aware Calibration)

**来源**: RegimeFolio (VIX-based classifier) + DeepCal (condition-aware variable estimator) + FinPFN (meta-learning without explicit regime labels)

**问题**: 当前 L1 校准上下文计算 7 天滚动精度，不区分市场制度。在低波动制度下 70% 精度的模型，在高波动制度下可能只有 30%，但校准上下文把两者平均了。

**方案**:
```
市场制度分类 (纯计算, 零 LLM):
  - VIX < 15: LOW_VOL (低波动)
  - VIX 15-25: NORMAL (正常)
  - VIX 25-35: HIGH_VOL (高波动)
  - VIX > 35: CRISIS (危机)

校准上下文调整为:
  "当前制度: NORMAL (VIX=18.2)
   在 NORMAL 制度下, 过去 30 天方向精度: 12/18 (67%)
   在所有制度下, 过去 30 天方向精度: 14/25 (56%)
   → 当前制度精度好于平均, 可以适度提高置信度"
```

**MarketMind 适配**:
- Fragility Scanner 已经追踪 VIX 阈值 (`config/fragility_thresholds.py` 中包含 VIX 指标)
- 扩展 `daily_calibration.py` 的 `compute_calibration_context()`: 按制度分组统计
- 无需 LLM 调用，纯计算

**预期收益**: 精度从 "全制度平均" 升级为 "制度条件精度"，置信度更准

---

### 机制 3: 结构化验证反馈 (Structured Verification Feedback)

**来源**: LinkedIn Autopilot (generate→score→hint→regenerate) + Feedback Over Form (execution feedback dominates topology)

**核心洞察**: 
- 结构化、分类、优先级排序的反馈远比二元 pass/fail 有效
- 不同类型错误的可修复率差异巨大: assertion errors 40-60% vs deep logic errors <5%
- 第一轮优化的收益占比 >90%

**问题**: 当前 MarketMind 的 SHARP 规则进化只在精度持续性 <45% 时触发，触发条件太苛刻。大量 "中等性能" 的 Stage 从不获得针对性反馈。

**方案**:
```
每个 Stage 输出后 → 结构化反馈标签 (非 LLM, 纯规则):
  - STRUCTURE_OK / STRUCTURE_MALFORMED (输出格式是否正确)
  - CONFIDENCE_CALIBRATED / OVERCONFIDENT / UNDERCONFIDENT
  - EVIDENCE_LINKED / UNSUBSTANTIATED_CLAIM
  - CONTRADICTION_FREE / SELF_CONTRADICTING
  - ACTIONABLE / VAGUE

反馈优先级:
  1. STRUCTURE_MALFORMED → 立即重新生成 (cheap check)
  2. SELF_CONTRADICTING → flag 给 Red Team
  3. UNSUBSTANTIATED_CLAIM → 降低该 Stage 置信度权重
  4. OVERCONFIDENT → 触发 Platt 重新拟合
```

**MarketMind 适配**:
- 在 Stage 3-8 每个 Stage 的 LLM 输出后追加结构化检查
- 使用正则 + 规则引擎（零 LLM），不是 LLM-as-judge
- 反馈标签写入 daily_snapshot，供周审计和 SHARP 进化使用

**预期收益**: 可操作的反馈信号 → 更快定位问题 Stage → SHARP 进化触发更精准

---

### 机制 4: LLM 断路器 (LLM Circuit Breaker)

**来源**: ROT 3-failure cutoff + LinkedIn progressive hardening

**问题**: 当前 MarketMind 每个 Stage 内部有 try/except → fallback，但这个 fallback 是**被动的**（API 调用失败后）。没有**主动的**断路器——当 API 连续返回低质量输出时，继续重试只是在浪费 token。

**方案**:
```
每个 Stage 的 LLM 调用包装:
  连续 N 次返回:
    - 空响应
    - JSON 解析失败
    - 置信度 < 阈值
    - 输出长度 < 最小值
  → 断路器 OPEN
  → 跳过该 Stage（使用 fallback default）
  → 发送 Alert
  → 5 分钟后 HALF_OPEN（允许 1 次探测调用）
  → 成功 → CLOSED / 失败 → OPEN (2x 冷却时间)
```

**MarketMind 适配**:
- Gateway 层已有 `CircuitBreaker` 用于 HTTP 错误
- 新增 `QualityBreaker` 用于输出质量断路
- 在 `orchestration.py` 的每个 `_do_*` 函数中检查

**预期收益**: 防止 token 预算在低质量输出上耗尽

---

### 机制 5: 多臂老虎机 Stage 选择 (Multi-Armed Bandit Stage Selection)

**来源**: R&D-Agent(Q) Linear Thompson Sampling + Adaptive Coopetition UCB mechanism

**问题**: 当前 MarketMind 的 Stage 顺序是固定的。但某些市场条件下，某些 Stage 的边际贡献可能为零（例如：单边上涨市场，Red Team 的 adversarial challenge 几乎没有价值）。

**方案**:
```
不是 "跳过或执行" 的二元选择（当前 L1 早停），而是 "应该分配多少 token budget 给每个 Stage" 的连续选择:

每个 Stage 的 "价值" = 该 Stage 对最终决策改动的幅度 × 改动的方向正确率

如果 L2 在 NORMAL 制度下连续 N 天不改动 L1 的输出:
  → L2 的 "信息价值" 下降
  → L2 的 max_tokens 从 16384 降到 8192 (节省成本但不完全跳过)
  → 如果 L2 的价值回升 → 恢复 max_tokens

使用 Thompson Sampling:
  - 每个 Stage 有一个 Beta(α, β) 分布 (α=改进次数, β=未改进次数)
  - 每次运行采样 → 根据采样值分配 token budget
```

**MarketMind 适配**:
- 难度较高，需要跟踪 "每个 Stage 对最终决策的增量贡献"
- 第一步: 在 brief 中记录 Stage 间 delta (L1→L2→Decision 的改动量)
- 第二步: 用这些 delta 训练 bandit

**预期收益**: token budget 动态最优化，不需要固定 60/40 split

---

### 机制 6: Headroom Test (优化前诊断)

**来源**: "Prompt Optimization Is a Coin Flip" (arXiv:2604.14585, 2026 年 4 月)

**核心发现**: 
- 72 次 prompt 优化运行中，49% 得分低于 zero-shot baseline
- 10 分钟 "headroom test" 可以预测优化是否值得
- 优化仅在存在 "可利用结构"（模型能产生但默认不产生的输出格式）时有帮助

**问题**: 当前 MarketMind 的 SHARP 规则进化是**全自动**的——只要有持续性精度差，就触发进化。但研究发现，prompt 优化在很多情况下只是随机扰动，没有真正的改进。

**方案**:
```
触发 SHARP 进化前，先跑 Headroom Test:

1. 生成 12-20 个候选 prompt 变体 (用 Flash, 成本极低)
2. 在 calibration 数据上评估每个变体的精度
3. 如果 best variant > current prompt + 等值点 (2%):
   → 值得优化, 触发完整 SHARP 进化
4. 否则:
   → 问题不在 prompt, 在数据质量/模型能力/市场随机性
   → 跳过 prompt 优化, 转而检查数据源健康度
```

**MarketMind 适配**:
- 在 `methodology_evolution.py` 的 `run_cross_stage_attribution()` 之前插入
- 使用 Flash (廉价) 生成候选变体, 在历史 calibration 数据上评估
- 如果 headroom test 失败 → 不触发 SHARP, 改为记录 "NO_HEADROOM" 事件

**预期收益**: 避免无效的 prompt 优化，节省 Pro 调用 + 防止规则退化

---

## 三、不推荐引入的机制 (及原因)

| 机制 | 不推荐原因 |
|------|------|
| **DSPy/TextGrad 自动 prompt 优化** | 研究发现 joint optimization 统计上不必要；MarketMind 的 prompt 结构已经稳定，自动优化收益有限 |
| **Multi-Agent Debate (ColMAD/AdCo)** | MarketMind 已有 Red Team + Contrarian Challenge + Shadows，多 Agent 辩论在此之上边际收益小 |
| **Meta-Learning (FinPFN)** | 需要微调模型权重，MarketMind 使用 API 调用 DeepSeek，无法访问模型权重 |
| **Particle Filter 制度切换** | 过于复杂，VIX-based 简单分类已足够 |
| **Self-Training (SePT)** | 需要训练数据累积 + 模型微调，MarketMind 目前阶段不适用 |

---

## 四、推荐实施优先级

| 优先级 | 机制 | 复杂度 | 预期收益 | 依赖 |
|:--:|------|:--:|:--:|------|
| **P0** | 制度感知校准 | 低 | 中 | Fragility Scanner 已有 VIX |
| **P0** | LLM 断路器 | 低 | 高 | Gateway 已有 CircuitBreaker |
| **P1** | 自适应信号抑制门 | 中 | 中 | 需要累积信号历史数据 |
| **P1** | Headroom Test | 中 | 高 | SHARP 进化框架 |
| **P2** | 结构化验证反馈 | 中 | 中 | 需要定义反馈标签体系 |
| **P2** | MAB Stage 选择 | 高 | 高 | 需要 Stage 间 delta 追踪 |

---

## References

| # | Source | Date | Type |
|---|--------|------|------|
| 1 | [Adaptive Data Flywheel: MAPE Control Loops for AI Agent Improvement](https://aclanthology.org/2026.eacl-industry.33/) | 2026-04 | `[V]` primary |
| 2 | [Prompt Optimization Is a Coin Flip](https://arxiv.org/abs/2604.14585) | 2026-04 | `[V]` primary |
| 3 | [ROT-TECH-PDF (Reddit Options Trader)](https://github.com/Mattbusel/ROT-TECH-PDF) | 2025 | `[V]` primary |
| 4 | [R&D-Agent-Quant: Multi-Agent Framework for Data-Centric Factors](https://bytez.com/docs/neurips/121804/paper) | 2025 | `[V]` primary |
| 5 | [RegimeFolio: Regime Aware ML System](https://arxiv.org/abs/2510.14986) | 2025-09 | `[V]` primary |
| 6 | [FinPFN: Meta-Learning for Return Prediction in Shifting Regimes](https://www.sciencedirect.com/science/article/abs/pii/S1386418125000825) | 2025-11 | `[V]` primary |
| 7 | [Adaptive Coopetition: Coarse Verifier Signals for Multi-Agent LLM Reasoning](https://aclanthology.org/2025.ijcnlp-srw.13/) | 2025 | `[V]` secondary |
| 8 | [Collaborative Multi-Agent Debate in Error Detection](https://arxiv.org/abs/2510.20963) | 2025-10 | `[V]` secondary |
| 9 | [metaTextGrad: Automatically optimizing language model optimizers](https://arxiv.org/abs/2505.18524) | 2025-10 | `[V]` secondary |
| 10 | [SIA: Self Improving AI Framework](https://github.com/hexo-ai/sia) | 2026 | `[V]` secondary |
| 11 | [Market Regime Detection using HMM](https://github.com/Sakeeb91/market-regime-detection) | 2026-01 | `[V]` secondary |
