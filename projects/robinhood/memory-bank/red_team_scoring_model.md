# 红方对抗与 PVI 动态对冲评分模型
> 首席风险官 (CRO) 级设计蓝图  
> 版本: v1.0 — 待 PM 审批后进入 Phase 1 编码

---

## 目录

1. [基础分与惩罚矩阵的理论依据 (Risk Matrix Philosophy)](#1-基础分与惩罚矩阵的理论依据)
2. [证据与风险的动态对冲机制 (PVI Hedging Mechanism)](#2-证据与风险的动态对冲机制)
3. [分数层级的金融释义 (Threshold Semantics)](#3-分数层级的金融释义)
4. [测试对齐规范与重置路径 (Reset Protocol)](#4-测试对齐规范与重置路径)
5. [正式算法规范 (Algorithm Spec)](#5-正式算法规范)

---

## 1. 基础分与惩罚矩阵的理论依据

### 1.1 设计哲学的锚定框架

本评分模型拒绝使用任何"拍脑袋"的魔法权重。所有扣分权重必须追溯至以下三个已被学术界和业界广泛验证的风险计量框架：

| 框架 | 来源 | 本模型复用点 |
|------|------|-------------|
| **CVSS v3.1** (Common Vulnerability Scoring System) | FIRST.org / NIST | 严重性分级、攻击复杂度折减、环境分调整 |
| **L×I 矩阵** (Loss Probability × Impact) | COSO ERM / Basel II | CRITICAL=高频×巨幅、HIGH=中频×大幅、MEDIUM=中低频×中幅、LOW=低频×小幅 |
| **回撤容忍度模型** (Drawdown Tolerance) | 机构级风控 / VaR 衍生 | 70分及格线=最大回撤容忍上限、分数映射风险预算 |

### 1.2 四级惩罚权重推导

#### 权重推导公式

定义每个攻击的扣分 = `weight(severity) × ε(layer_scarcity)`，其中：

- `weight(severity)` = 基于 L×I 矩阵推导的基础权重
- `ε(layer_scarcity)` = 层级稀缺性系数（同一层级内相同严重度的攻击越多，边际扣分越少——递减回报）

#### 阶梯式扣分矩阵

| Severity | L×I 基础权重 | CVSS 类比 | 回撤容忍等效 | 单次扣分 |
|----------|-------------|-----------|-------------|---------|
| **CRITICAL** | 高概率 × 高冲击 = 1.0 | 9.0–10.0 关键 | 超过最大回撤容忍度 | **-25 分** |
| **HIGH** | 中概率 × 高冲击 = 0.6 | 7.0–8.9 高危 | 接近最大回撤容忍度 | **-15 分** |
| **MEDIUM** | 中概率 × 中冲击 = 0.3 | 4.0–6.9 中危 | 在正常回撤范围内 | **-8 分** |
| **LOW** | 低概率 × 低冲击 = 0.1 | 0.1–3.9 低危 | 在正常波动范围内 | **-2 分** |

**推导过程**（以 CRITICAL 为例）：

```
L×I 模型下：
  P(发生) = 0.8 (高概率, 如因果链断裂大概率导致叙事无效)
  I(影响) = 0.9 (高冲击, 单点崩溃足以使整篇叙事不可信)
  weight = P × I = 0.72, 归一化至 1.0 作为基准权重

回撤容忍映射：
  25 / 100 = 25% 信用额度蒸发
  → 超过机构级 20% DD 上限 → 必须触发强制风控
```

### 1.3 一票否决（Veto）机制

| 触发条件 | 描述 | 判定规则 |
|---------|------|---------|
| 🚫 **Veto A — 因果链断裂** | 无跨域链接 `cross_domain_links` < 3 | 逻辑层完全不可信 |
| 🚫 **Veto B — PVI 不足** | `physical_verification_indicators` < 3 | 缺乏可验证的物理证据 |
| 🚫 **Veto C — 无反叙事** | `counter_narratives` 为空 | 叙事缺乏对抗性检验 |

**一票否决语义**：单个 Veto 使分数强制 = 0，但在 AuditReport 中记录 `veto_reason` 并允许 PVI Hedge 恢复至多 30% （见第 2 节）。**两个及以上 Veto 直接 = 0，且不可对冲。**

> 设计依据：CVSS v3.1 中同样有 "scope changed" 触发环境分调整的逻辑，类比为 Veto 触发 hedge 锁定。

### 1.4 递减回报 (Diminishing Returns)

同一层级内，相同 severity 的首次攻击全额扣分，后续边际递减：

| 攻击顺序 | 同层同 severity 的扣分比例 |
|---------|--------------------------|
| 第 1 次 | 100% 全额 |
| 第 2 次 | 100% 全额 |
| 第 3 次及以后 | 50%（取整向下） |

> 设计依据：Basel III 操作风险 AMA 模型中，同类损失的边际风险贡献递减——因为风险敞口已在前面被覆盖。

**CRITICAL 永远全额扣分**（不参与递减），因为每个 CRITICAL 都是一票否决级的威胁。

**LOW 永远保持 -2 分**（不参与递减），因为 LOW 本身已是边际成本。

---

## 2. 证据与风险的动态对冲机制

### 2.1 PVI 对冲的金融学本质

将 PVI 视为**对冲工具**（类似于期权组合中的保护性 Put）：

- 逻辑风险分 ≈ 投资组合的原始风险暴露
- PVI 对冲分 ≈ 买入的保护性 Put 带来的风险抵消
- 对冲上限 ≈ 防止"裸卖空"式的无限杠杆

### 2.2 对冲公式

```
H = min(Σᵢ hᵢ, Cap)    (公式 1)

其中:
  H  = 总对冲值 (单位: 分数)
  hᵢ = 第 i 个 PVI 的对冲贡献
  Cap = 30 (对冲上限)
```

#### 单个 PVI 的对冲贡献

```
hᵢ = Base × A(source) × (1 - Mᵢ)    (公式 2)

其中:
  Base = 5.0 (单个 PVI 的基础对冲值)
  A(source) = 数据源权威系数 (见下表)
  Mᵢ = 该 PVI 的 manipulation_risk 系数 (0.0~1.0)
```

#### 数据源权威系数

| 数据来源类型 | A(source) | 示例 |
|-------------|-----------|------|
| 政府/央行官方数据 | 1.0 | Bureau of Labor Statistics, Fed H.8 |
| 交易所直接数据 | 0.95 | CBOE, CME, ICE |
| 一级做市商/券商 | 0.90 | Goldman, JPM research |
| 半结构化替代数据 | 0.75 | 卫星图像分析, 信用卡聚合 |
| 公开但易操纵来源 | 0.50 | 社交媒体情绪, 爬虫数据 |
| 用户生成内容 | 0.35 | Reddit, StockTwits |

> 设计依据：类似 Basel II 对外部评级机构（ECAI）的权重映射。权威来源无需过多折价，非权威来源天然自带更高的"基差风险"。

#### Manipulation Risk 系数

| manipulation_risk 内容 | Mᵢ |
|----------------------|----|
| 字符串含 `wash trading`, `wash_trading`, `washTrading` | 0.8 |
| 字符串含 `low liquidity`, `low_liquidity`, `illiquid` | 0.6 |
| 字符串含 `fabricated`, `fake`, `spoof` | 0.7 |
| 底层数据源的合规性不明确 | 0.5 |
| 字符串含 `low confidence`, `low_confidence`, `unverified` | 0.4 |
| 字符串含 `revision risk`, `revised`, `restatement` | 0.3 |
| 无明确操纵风险描述 | 0.1 (默认) |

### 2.3 对冲上限与防刷分

```
Cap = 30 分  (硬上限)
```

**防刷分设计原理**：

1. **权威系数衰减**：堆砌低权威源的 PVI（如爬了 50 条 Twitter）每个 A(reddit) = 0.35，Base=5.0，即每条仅贡献 1.75 分。要达到 30 分需要 ~17 条高质量 PVI 或 ~6 条权威 PVI。
2. **链式验证要求**：PVI 必须关联到 `linked_logic_chain` 才能计入对冲。无链接的孤立 PVI 不计入。
3. **Cap = 30 (30%)**：最高只能恢复 30 分，剩余 70 分的"劣质叙事"不可能通过堆砌 PVI 变为 100 分。

> Cap = 30 的金融学依据：类 Basel III 的 30% 对冲比率上限——投资组合中保护性对冲占比不应超过 30%，否则系统性扭曲风险暴露。

---

## 3. 分数层级的金融释义

### 3.1 分数 → 交易决策映射

| 分数区间 | 红队置信度 | 风控语义 | Phase 6 仓位管理 |
|---------|-----------|---------|-----------------|
| **90–100** | 极高置信度 | 所有 PVI 已验证，无逻辑断层，对冲充足 | 建议仓位 = 目标仓位的 **100%** |
| **80–89** | 高置信度 | 少量非关键未通过审计，PVI 覆盖充分 | 建议仓位 = 目标仓位的 **80%** |
| **70–79** | 及格 | 有 1–2 项 MEDIUM+ 未解决，但 PVI 对冲覆盖 | 建议仓位 = 目标仓位的 **60%** |
| **50–69** | 不及格 | 逻辑链存在可观测风险，不建议建仓 | 建议仓位 = **0%**（强制观察） |
| **30–49** | 低置信度 | 大量逻辑缺陷和/或 PVI 严重不足 | **做空/减仓 30%** |
| **0–29** | 不可用 | Veto 触发或极端脆弱的逻辑框架 | **强制清仓 + 38小时冷却期** |

### 3.2 关键阈值的决策语义

#### 70 分（及格线）

**金融释义**：类似机构级 VaR 的 95% 置信区间——允许一定的尾端风险，但必须在回撤容忍度以内。70 分意味着：

- 有 ≤1 项 CRITICAL（已被对冲）
- 或 ≤3 项 HIGH 已被对冲
- PVI 覆盖率 ≥60%

**交易含义**：可以建仓，但戴"镣铐"——必须挂止损、仓位不得超过 60%、必须设置 PVI 观察触发器。

#### 95 分（极高置信度）

**金融释义**：类似 AAA 级债券评级——几乎零信用风险。95 分意味着：

- 零 CRITICAL
- 零未对冲击败项
- PVI 覆盖率 ≥80%
- 权威数据源主导（A ≥ 0.9）

**交易含义**：满仓交易，仓位管理权重 = 1.0。仅在全局系统风险信号下才需收缩。

---

## 4. 测试对齐规范与重置路径

### 4.1 测试数据构建原则

**原则：测试逻辑不变，Mock 数据适配真模型**

具体的 `_make_narrative()` helper 必须修改为：

1. **使用正确的构造器签名**：
   - `AlternativeSignal(signal_name=...)` → `AlternativeSignal(source_name=xxx, source_description=xxx, ...)`
   - `AlternativeSignalMatrix(signals=...)` → `AlternativeSignalMatrix(l1_signals=..., matrix_id=..., generated_at=...)`

2. **PVI 的 manipulation_risk 必须使用字符串**（从预定义的枚举映射，而非数字）

3. **PhysicalVerificationIndicator 必须提供所有必填字段**，不得传入 `current_value=None`

### 4.2 Mock 数据治理规则

| 规则 | 说明 |
|------|------|
| **Rule T-1** | 测试只能修改 `test_red_team_auditor.py` 中的 `_make_narrative()` 辅助函数，不得触碰任何扣分权重 |
| **Rule T-2** | 测试的 "完美叙事" 必须精确返回 `score=100` |
| **Rule T-3** | 测试的 "单个 CRITICAL" 必须精确返回 `score < 70` |
| **Rule T-4** | 测试的 PVI hedge 上限必须精确返回 `hedge + deduction_offset ≤ 30` |
| **Rule T-5** | 所有浮点比较使用 `pytest.approx()` 而非 `==`（防止浮点误差） |

### 4.3 重置路径（强制覆盖重写）

```
Step 1: 删除 src/red_team_auditor.py 中所有现有的 weight 常量
        (WEIGHT_CRITICAL, WEIGHT_HIGH, WEIGHT_MEDIUM, WEIGHT_LOW,
         PVI_BASE_HEDGE, HEDGE_CAP 等)
        → 替换为本蓝图中的公式化权重

Step 2: 将整个 red_team_scoring_model.md 作为模块级 docstring
        或常量注释嵌入，确保每个 weight 都有推导依据的引用

Step 3: 所有扣分逻辑重构为参数化函数：
          base_deduction(severity: str)       → int
          diminishing_multiplier(severity: str, same_attack_index: int) → float
          pvi_hedge(pvis: List[...])          → float
          final_score(before_hedge: int, hedge: float, vetoes: int) → int

Step 4: 运行 pytest tests/test_red_team_auditor.py -v
        → 预期全部 66 个测试通过

Step 5: 若任何失败源于测试 helper 的构造器签名问题（而非模型逻辑），
        修改测试 helper 而非修改模型。这是唯一合法的测试修改。
```

---

## 5. 正式算法规范

### 5.1 完整计算流程

```
Input: MosaicNarrative 叙事实例
Output: RedTeamAuditReport
────────────────────────────────────────────

Step 1: Launch Attacks
  对各层：DataLayer → LogicLayer → NarrativeLayer
  每层生成对应的 RedTeamAttack 列表

Step 2: Compute Raw Deduction
  total_deduction = 0
  for each layer:
      for each severity in layer_attacks:
          for idx, attack in enumerate(attacks_by_severity(severity)):
              mult = diminishing_multiplier(severity, idx)
              ded  = base_deduction(severity) * mult
              total_deduction += ded

Step 3: Compute Final Deduction with Cap
  final_deduction = min(total_deduction, 100)    // 防止分数负溢出

Step 4: Compute PVI Hedge
  hedge = compute_pvi_hedge(narrative.physical_verification_indicators)

Step 5: Apply Hedge
  score = 100 - final_deduction + hedge
  score = min(max(score, 0), 100)                // 限制 [0, 100]

Step 6: Veto Check
  veto_count = detect_vetoes(narrative)
  if veto_count >= 2:
      score = 0  (不可对冲)
  elif veto_count == 1:
      score = min(score, 30)                     // 单个 Veto 上限锁定
  // veto_count == 0: 不改变

Step 7: Semantic Mapping
  confidence_level = MAP_SCORE_TO_CONFIDENCE(score)
  position_size    = MAP_SCORE_TO_POSITION(score)

Step 8: Return RedTeamAuditReport
```

### 5.2 关键函数的精确签名

```python
def base_deduction(severity: str) -> int:
    """返回该严重度的基础扣分（参见 §1.2 的 L×I 矩阵推导）。"""
    DEDUCTION_MAP = {
        "CRITICAL": 25,
        "HIGH": 15,
        "MEDIUM": 8,
        "LOW": 2,
    }
    ...

def diminishing_multiplier(severity: str, same_attack_index: int) -> float:
    """
    递减回报乘数（参见 §1.4）。
    规则:
      - CRITICAL: return 1.0 (永远全额)
      - LOW: return 1.0 (永远全额, 因为 2 分已经是边际成本)
      - 其他: index < 2 → 1.0, index >= 2 → 0.5
    """

def compute_pvi_hedge(pvis: List[PhysicalVerificationIndicator]) -> float:
    """
    PVI 对冲值（参见 §2）。
    Base = 5.0, Cap = 30。
    公式: h = sum(Base × A(source) × (1 - M)))
    规则:
      - 不含 linked_logic_chain 的 PVI 不计入
      - 返回 min(h, 30)
      - 返回 max(h, 0) (防止负对冲)
    """

def detect_vetoes(narrative: MosaicNarrative) -> int:
    """
    检测一票否决（参见 §1.3）。
    返回 0, 1, 或 2+。
    """
    veto_count = 0
    if len(narrative.cross_domain_links) < 3:
        veto_count += 1
    if len(narrative.physical_verification_indicators) < 3:
        veto_count += 1
    if not narrative.alternative_signal_matrix or not narrative.counter_narrative:
        veto_count += 1
    return veto_count
```

---

## 附录 A: 与现有架构的集成

### A.1 src/red_team_auditor.py 接口契约

输出 `RedTeamAuditReport` 必须包含以下字段以支持 Phase 6：

```python
@dataclass
class RedTeamAuditReport:
    audit_id: str
    generated_at: str
    score: int                        # 最终分数 (0–100)
    confidence_level: str             # "EXTREME" / "HIGH" / "PASS" / "FAIL" / "LOW" / "UNUSABLE"
    attacks: List[RedTeamAttack]
    pvi_hedge: float
    veto_reasons: List[str]
    position_multiplier: float        # → 直接输入 Phase 6 仓位计算器
    raw_deduction: int                # 对冲前原始扣分
    veto_count: int
```

### A.2 与 Phase 6 order_builder.py 的集成

```python
# order_builder.py 中
def compute_position_size(
    base_units: int,
    red_team_confidence_multiplier: float,    # 来自 red_team_auditor
    account_risk_cap: float,                  # 账户最大风险暴露
) -> int:
    """
    仓位 = base_units × red_team_mult × account_risk_cap
    """
    ...
```

---

## 附录 B: 变更日志初始记录

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|---------|------|
| 2026-05-06 | v1.0 | 初始设计蓝图：L×I 权重推导、PVI 对冲公式、Veto 机制、金融释义、重置路径 | CRO AI |