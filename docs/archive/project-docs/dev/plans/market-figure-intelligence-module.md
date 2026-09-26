# 市场人物与社交媒体情报模块

**版本**: 1.0
**日期**: 2026-05-20
**状态**: 已通过红方审计并修复（v1.1）
**依赖**: `config/key_persons.py`, `pipeline/insider_sources.py`, MCP `@anguslin/mcp-capitol-trades`

---

## 1. 模块目的与定位

### 1.1 问题

- 市场人物（央行行长、政治人物、CEO、基金经理、名人）的言论和行为可以显著影响资产价格
- 当前系统只通过一般新闻源被动获取这类信号，缺乏结构化追踪
- `config/key_persons.py` 已定义 7 人但未系统化

### 1.2 定位

信息架构的第 5 层——人物情报层。产出 `FigureSignal` 对象，同时输入主管道 Flash 分诊和影子生态。

### 1.3 设计原则

| # | 原则 |
|:--:|------|
| 1 | 能力×意愿×市场承认 = 信号有效值。三个维度缺一不可。 |
| 2 | 区分信号成本类型——真金白银的行动 > 口头表态 |
| 3 | 前四类人物 = 方向性信号；后两类 = 确认/反向指标 |
| 4 | 所有信号经事件研究法验证后才计入历史准确率 |
| 5 | 对国会交易、SEC 备案等有法律风险的数据源仅使用公开信息 |

---

## 2. 市场人物分类体系

| 大类 | 子类 | 信号方向 | 预期效应量级 | 示例 |
|------|------|:--:|:--:|------|
| I. 政策制定者 | 央行行长、财政部长 | 方向性 | 50-200bp | Powell, Lagarde, Ueda |
| II. 政治人物 | 总统/总理、贸易代表 | 方向性 | 25-50bp | Trump, 内阁关键成员 |
| III. 企业高管 | 大市值CEO/创始人 | 方向性 | 不定 | Elon Musk, Jensen Huang |
| IV. 活动家投资者 | 对冲基金活动家 | 方向性 | ~700bp CAR | Elliott, Starboard, Icahn |
| V. 基金经理 | 桥水/Baupost级 | 确认/滞后 | 中等 | Buffett(13F), Burry, Dalio |
| VI. 名人/网红 | 顶流KOL | 反向/噪声 | <25bp 快速逆转 | 现有finfluencers |

**交互效应**: 同一资产被多类人物同时提及 → 信号叠加增强。

---

## 3. 信号评分框架 (A×W×A)

### 3.1 公式

```
Final_Score = (Ability + 0.01) × (Willingness + 0.01) × (Acknowledgment + 0.01)  # Laplace 平滑防零乘子
阈值（初始校准值，Phase 4 季度重校准后替换）: ≥0.6 → HIGH; 0.3-0.6 → MEDIUM; <0.3 → LOW
新人物默认值: 央行行长 Ability=0.7, 政治人物=0.5, CEO=0.5, 基金经理=0.4, 名人=0.2
```

### 3.2 能力 (Ability)

| 子维度 | 权重 | 量化方法 |
|------|:--:|------|
| 信息优势（距决策链距离） | 0.40 | 职位评分：FOMC投票委员=1.0, 非投票=0.5, 外部=0.2 |
| 历史准确率 | 0.35 | 过去 N 次发言/行动后市场方向一致率 |
| 机构地位（AUM/政策权限） | 0.25 | 归一化到 [0,1] |

### 3.3 意愿 (Willingness)

基于 Kartik, Ottaviani & Squintani (2007) 的有成本沟通模型：

| 子维度 | 权重 | 量化方法 |
|------|:--:|------|
| 仓位一致性（说的和做的一致吗？） | 0.40 | 言论方向 vs 个人持仓方向对比 |
| 行动跟进（历史上是否跟进？） | 0.35 | 过去言论→实际行动转化率 |
| 声誉风险（错了代价多大？） | 0.25 | 监管风险敞口、公众关注度 |

**信号成本层级**:
- L4 (最高): 真实持仓 + SEC监管风险，e.g., Form 4 内部人购买
- L3: 13F 披露 + 基金持仓
- L2: 官方讲话 (FOMC声明、国会证词)
- L1: 社交媒体帖子 (有一定声誉风险)
- L0 (最低): 匿名/非正式言论

### 3.4 市场承认 (Acknowledgment)

通过事件研究法测量：

| 子维度 | 权重 | 方法 |
|------|:--:|------|
| 统计显著性 | 0.30 | CAR t-test p<0.05 |
| 效应量 | 0.30 | \|CAR\| > 0.25% |
| 持续性 | 0.20 | 5日窗口不逆转 |
| 多资产确认 | 0.20 | ≥2 资产类别同步反应 |

---

## 4. 追踪人物清单

### 4.1 已有基础（key_persons.py, 7人）

| 人物 | 信号方向 | 平台 | 数据源 |
|------|:--:|------|------|
| Donald Trump | 方向性 | Truth Social, X | trumpstruth.org RSS |
| Keith Gill (Roaring Kitty) | 方向性 | X, YouTube, Reddit | PRAW, X API |
| Elon Musk | 反指 | X | X API |
| Graham Stephan | 反指 | YouTube | — |
| Jeremy Lefebvre | 反指 | YouTube | — |
| Andrei Jikh | 反指 | YouTube | — |
| George Gammon | 反指 | YouTube | — |

### 4.2 优先新增

**P0 (立即)**:
| 人物 | 类别 | 原因 |
|------|:--:|------|
| Jerome Powell | I | Fed Chair，每次讲话市场必须反应 |
| Christine Lagarde | I | ECB President |
| Kazuo Ueda | I | BOJ Governor，日元套利交易关键 |
| Nancy Pelosi | II | 国会交易量最大、最受关注 |
| Warren Buffett | V | 13F 持仓是价值投资风向标 |

**P1 (短期)**:
- FOMC 当年投票委员（约5人）
- PBOC Governor
- BOE Governor
- 国会交易活跃的前10议员（MCP Capitol Trades自动获取）
- Michael Burry (Scion 13F)
- Ray Dalio (桥水宏观观点)

**P2 (中期)**:
- Jensen Huang (NVDA), Tim Cook (AAPL), Satya Nadella (MSFT)
- Carl Icahn, Bill Ackman
- 做空机构: Muddy Waters, Hindenburg successor
- 大型基金13F: BlackRock, Vanguard, Citadel, Renaissance

---

## 5. 数据源设计

### 5.1 已有源

| 源 | 类型 | 状态 |
|------|------|:--:|
| trumpstruth.org RSS | Truth Social | ✅ 生效 |
| SEC Form 4 (EDGAR Atom) | 内部人交易 | ✅ insider_sources.py |
| SEC 13F (EDGAR Atom) | 机构持仓 | ✅ insider_sources.py |
| 内部人集群检测 | 3+, 同ticker, 14天 | ✅ insider_sources.py |

### 5.2 国会交易

**MCP `@anguslin/mcp-capitol-trades`** (免费):
- 按政治家/票/党/交易类型/时间范围查询
- 最热交易标的排名
- 买卖动量资产
- 回退: `tools/manual_congress.py` (手动录入JSONL)

### 5.3 社交媒体

| 平台 | 方案 | 优先级 | 状态 |
|------|------|:--:|:--:|
| Truth Social | trumpstruth.org RSS（已有） | P0 | ✅ 生效 |
| X (Twitter) | X API 无免费层（2026年2月起）。替代：RSSHub 自托管 X→RSS 转换。无 API 时依赖 X 的人物自动降级为"间接追踪"（通过新闻源提及） | P1 | ⚠️ 受限 |
| Reddit | PRAW (free, 60 req/min) | P2 | — |
| YouTube | Google News RSS 间接监控（搜索 "{name} stock investment"） | P2 | ⚠️ 间接 |

### 5.4 央行日历

| 源 | 数据 | 成本 | 合规 |
|------|------|:--:|:--:|
| Fed 官网 RSS | 联邦储备委员会新闻稿（已有 source_authority.py） | 免费 | ✅ 官方 |
| ECB 官网 RSS | 欧洲央行新闻稿（已有 source_authority.py） | 免费 | ✅ 官方 |
| BOJ/BOE 官网 | 日本/英国央行声明 | 免费爬虫 | ✅ 官方 |
| ~~ForexFactory~~ | — | — | ❌ 放弃：ToS 禁止自动化 |
| ~~Econoday~~ | — | — | ❌ 放弃：ToS 禁止自动化 |

---

## 6. 事件研究管道

### 6.1 事件窗口（Phase 1: 仅日频）

```
帖子/声明时间戳 (UTC)
  │
  ├── 日度 [0, 0]      → AR_daily, AV_daily, AVR_daily
  └── 日度 [0, +1]     → CAR[0,+1]
```

日内窗口 `[0, +30min]` 延后至 Phase 3（`easy-event-study` 仅支持日频，分钟级数据需额外基础设施）。

### 6.2 模型

默认 CAPM 市场模型。可选 FF3/FF5。工具: `easy-event-study` (pip install) 或自实现。Ticker 映射：Flash LLM 从帖子文本提取受影响资产列表。

### 6.3 季度重校准

每季度更新每人的 CAR 基准、情绪-收益映射、影响力衰减因子。

---

## 7. 新闻推送策略

### 7.1 三級制

| 级别 | 分数 | 推送 | 类型 |
|:--:|:--:|------|------|
| Critical | ≥80 | 即时 (SLA ≤5min) | FOMC、央行讲话、重大政策 |
| High | 50-79 | 15分钟批次 | 财报、评级变更、交易披露 |
| Low | <50 | 每日摘要 | 一般评论 |

### 7.2 评分公式

```
Push_Score = 0.35×信源权威 + 0.35×市场意外 + 0.30×相关性匹配
最终分数 = Push_Score × A×W×A_Score(该人物)
```

### 7.3 影子过滤

- Fade Master: 所有情绪类信号
- Crash Hunter: 内幕集群、做空报告
- Expert 影子: 各自领域相关人物活动
- 其余影子: Tier 1 推送（极高分数）才接收

---

## 8. 系统集成

### 8.1 数据流

```
国会交易MCP / Social / SEC / 央行日历
        │
        ▼
  FigureSignalExtractor（纯Python + Flash LLM分类）
        │
        ├──→ 主管道 Flash Triage（作为额外信号类型 "figure_signal"）
        │
        ├──→ 影子生态（仅原始内容：帖子文本 + 发布者 + 时间戳。不传递 AWA 分数或信号方向）
        │    影子通过独立配额自行解读原始人物活动。遵守信息隔离规则。
        │
        └──→ Gate 2 "今日人物动态" 面板（含 AWA 评分，仅用户可见）
```

**隔离合规**：影子生态只接收原始社交媒体帖子文本（内容+发布者+时间戳），不接收 AWA 分数和信号方向。这遵守 MarketMind 信息广播规则——"影子接收原始新闻/事实，不接收主流分析/报告"。AWA 评分仅用于主管道和 Gate 2 用户展示。

### 8.2 FigureSignal 数据结构

```python
@dataclass
class FigureSignal:
    person_name: str
    category: str           # I-VI
    signal_direction: str   # "directional" | "contrarian" | "confirmatory"
    event_type: str         # "speech" | "trade" | "filing" | "social_post"
    ticker: str | None
    direction: str | None   # "long" | "short" | "warn"
    awa_score: float        # 0-1
    confidence: float
    summary: str            # Flash 生成的一句话摘要
    source_url: str
    timestamp: str
```

### 8.3 新模块

| 模块 | 文件 | 行数 | LLM? |
|------|------|:--:|:--:|
| FigureSignalExtractor | `pipeline/figure_signal.py` | ~200 | Flash(分类) |
| AWA Scorer | `pipeline/awa_scorer.py` | ~150 | 0 |
| EventStudyRunner | `pipeline/event_study_runner.py` | ~200 | 0 |
| FigureNewsPusher | `pipeline/figure_news_pusher.py` | ~100 | 0 |

### 8.4 修改现有文件

| 文件 | 改动 |
|------|------|
| `config/key_persons.py` | 7→40+ 人物 |
| `pipeline/flash_triage.py` | 接收 content_type="figure_signal" |
| `pipeline/insider_sources.py` | 替换国会死源为 MCP 调用 |
| `shadows/daily_briefing.py` | 加入"今日人物动态"栏目 |

---

## 9. 信号可靠性保障

### 9.1 六层过滤

| 层 | 方法 | 过滤内容 |
|:--:|------|------|
| L0 | 信源过滤 | 已知虚假账号、bot |
| L1 | 主题分类(LLM) | 非市场相关言论 |
| L2 | AWA评分 | 低分噪声 |
| L3 | 事件研究法 | 无显著市场影响 |
| L4 | 历史一致性 | 随机正确 |
| L5 | 文本质量+信息一致性（textstat + FinBERT 情感 + 与主流新闻 TF-IDF 相似度） | 合成/垃圾文本 |

### 9.2 噪声过滤

Trump RSS 源 ~90% 噪声率。预过滤：关键词匹配 → 主题分类 → AWA评分。仅 ~10% 进入下游。

### 9.3 影响力衰减

季度重校准检测影响力递减（如 Elon Musk 的市场影响力随时间下降的证据）。衰减 >30% → 降级信号权重。

### 9.4 冲突处理

同一资产被方向性人物看多 + 反指人物也看多 → 增强看空信号（因为反指同向 = 危险信号）。

---

## 10. 实施计划

### Phase 1: 基础管道 (5-7天)
- FigureSignal dataclass + AWA Scorer
- 扩写 key_persons.py (7→15人，P0)
- 国会 MCP 集成
- 事件研究法接入（easy-event-study）
- 8 tests

### Phase 2: 社交媒体接入 (4-5天)
- Truth Social RSS 解析
- X 平台方案确定+实现
- 噪声预过滤管道
- 6 tests

### Phase 3: 推送与集成 (3-4天)
- 三级推送系统
- Flash Triage 集成
- 影子过滤分发
- 5 tests

### Phase 4: 可靠性+扩展 (3天)
- textstat + FinBERT 可靠性过滤
- 季度重校准脚本
- 人物清单扩展到 40+
- 红方审计

**总计**: 15-19天 | ~25新测试 | PICA 覆盖

---

## 参考文献

| 文献 | 用途 |
|------|------|
| Acemoglu, Johnson & Kermani (2016) | 政治关联→6-12% CAR |
| Brav, Jiang, Partnoy & Thomas (2008) | 活动家投资者→~7% CAR |
| Gorodnichenko et al. | Fed 主席语调→200bp S&P 500 影响 |
| Kleczka (2020) | Trump 公司特定推文→±0.25% AR, +19% 交易量 |
| Keasey et al. (2025) | 网红帖子→短期价格变化，快速逆转 |
| Kartik, Ottaviani & Squintani (2007) | 有成本沟通模型（意愿量化基础） |
| Spence (1973) | 信号传递模型（能力量化基础） |
| easy-event-study | CAPM/FF3/FF5 CAR 计算工具 |
| textstat + FinBERT | 社交媒体内容可靠性过滤（替代已停更的 DeepTrust） |
| @anguslin/mcp-capitol-trades | 国会交易免费 MCP 数据源 |
