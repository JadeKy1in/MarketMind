# MarketMind Restart Guide — 2026-05-21

**Branch**: master | **Last push**: 待提交

---

## Restart Command

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。今天的任务：(1) 审批影子生态最终方案，审批通过后开始 Phase 1-4 实现；(2) 按 `shadow-information-sources.md` 的优先级清单，新增信息源并逐个验证其可用性和数据质量；(3) 日内交易研究写入最终方案。

---

## 2026-05-20 完成的工作

### 影子生态方案设计（完整）

**核心决策**：
- 策略原型三分类：Fundamental (16) + Momentum (4) + Contrarian "敢死队" (4) = 24 影子
- 分类维度 = 策略原型，不是风险水平。对标 Millennium/Citadel pod-shop
- 影子是独立虚拟基金经理，产出 ShadowDecision（不是 ShadowVote）
- 决策融合已删除，影子不投票
- 全球扫描无休眠，Contrarian 每天在不同市场找机会
- 所有影子每天必决策，min $100
- 主管道与影子不直接通信，用户是唯一桥梁
- 仅 DeepSeek Pro 做分析，独立性靠 Persona+温度+数据切片
- ConcentrationDetector 替代 CollusionDetector

**方案文档**：`shadow-ecosystem-final-plan.md`（用户重构版 + 红方修补，1193→1350+ 行）
**市场人物模块**：`market-figure-intelligence-module.md`（红方审核后已修）

### 30 个外网研究问题全部完成

5 批次 Agent 研究覆盖：毕业标准、Gate 2 交互、自循环进化、记忆持久化、信息源扩展、市场人物分类、信噪过滤、数据贪婪控制、人物推送策略、Momentum/Contrarian 数据预取、评估窗口优化、日内交易频率、GitHub 开源探索

### 红方审核

6 个 Agent 审核两份方案，共约 50 发现。阻塞问题已修入方案。

### 基础设施

- MCP: `.mcp.json` 配置 Context7 + Capitol Trades
- 国会交易: `npm install -g @anguslin/mcp-capitol-trades`
- 启动脚本: `D:\Claude Code\Claude Code.bat` 增加 MCP 健康检查
- 信息源: 10 项 $0 API 立即可用，6 项需短期建设

---

## 当前状态

### 影子生态方案

| 文档 | 状态 |
|------|:--:|
| `shadow-ecosystem-final-plan.md` | 用户重构版 + 红方修补合并完成，待最终红方复审 |
| `market-figure-intelligence-module.md` | 已修入 14 红方发现 |

### 待解决（用户决策）

- [ ] X API 无免费层：依赖 X 的人物（Musk, Gill 等 15-20 人）自动降级为"间接追踪"
- [ ] ForexFactory/Econoday 放弃：换用 Fed/ECB 官方 RSS

### 待实现（Phase 5-10）

16+ 新模块，构建顺序见方案 §18。关键模块：
- ConsensusExtractor, PendingSignalRegistry, EventTracker
- DiversityController, DPP Selector, VennAbersCalibrator, BrierDecomposition
- GraduationEngine, PostGraduationMonitor, FactorAnalyzer
- DataQualityValidator, APICounter

---

## 关键文件

| 文件 | 用途 |
|------|------|
| `.claude/plans/shadow-ecosystem-final-plan.md` | **影子生态权威文档** |
| `.claude/plans/market-figure-intelligence-module.md` | 市场人物情报模块 |
| `.claude/plans/shadow-introductions-zh.md` | 24 影子中文介绍 |
| `.claude/plans/shadow-information-sources.md` | 信息源逐影子映射 |
| `.mcp.json` | MCP 服务器配置 |
| `D:\Claude Code\Claude Code.bat` | 启动脚本 |

### 已弃用文档（已归档 `.claude/plans/archive/`）

`shadow-type-redesign-v3.md`, `shadow-lifecycle-framework.md`, `shadow-vote-removal-analysis.md`, `final-plan-core-architecture.md`, `final-plan-section-graduation.md`, `final-plan-section-interaction-memory.md`, `final-plan-section-evolution-data.md`, `shadow-user-interaction-framework.md`, `shadow-memory-persistence.md`

---

## 待续任务

### 信息源新增与验证（明天首要任务）

**背景**：`shadow-information-sources.md` 已逐影子列出信息缺口。`shadow-ecosystem-final-plan.md` §6.1 定义了数据预取清单（P01-P13）。

**立即可验证（VIABLE NOW，$0）**：
- FRED API 扩展（从 2 个系列 → ~30 个系列，覆盖 14 个影子）
- DeFiLlama TVL API（加密，免费无 Key）
- EIA 能源库存 API（免费，需注册 Key）
- USDA FAS PSD API（农产品供需，免费）
- NOAA NCEI API（气候/ENSO，免费无 Key）
- CoinMetrics Community API（链上数据，免费）
- Twelve Data（800 次/天，官方 API）
- Ken French Data Library（Fama-French 因子，基准数据，完全免费）

**需要短期建设（NEEDS WORK）**：
- AAII 情绪爬虫（每周四，约 1-2 天）
- iTick API 接入（LME 库存，免费层）
- yfinance 期货 ticker 映射（CBOT/ICE 农产品）

**验证流程**（每个源）：
1. 运行 API 调用/爬虫 → 确认返回数据
2. 交叉验证：与已知可靠源对比（如 FRED vs Yahoo）
3. 记录延迟、完整度、异常值频率
4. 更新 `source_authority.py` 的 SourceStatus

**目标**：明天至少验证 5 个 VIABLE NOW 源并接入数据管道。

### 日内交易频率（研究已完成，方案待写入）

**Agent 研究结论**：
- 日内猎手（Intraday Scalper）适合双时点：开盘后 30 分钟 + 收盘前 30 分钟（Gao et al. 2018 学术支撑最强）
- 均值回归策略高频下表现更好（5min），趋势跟踪高频下恶化
- 脚本方式：yfinance 定时拉取 → 免费指标计算 → 仅信号触发时调用 Pro
- 增量成本 ~$1-2/月
- 多频率排名：统一年化至日频，用 Calmar+MaxDD（频率无关指标）

**相关文件**：`shadow-introductions-zh.md`（日内猎手），`shadow-ecosystem-final-plan.md`（待补入 §5 或新 §20）

### 信息流设计（待补入方案）
- Momentum/Contrarian 新闻推送策略（结构化指标优先，非自然语言新闻）
- 数据菜单配额制防贪婪/恐惧（§6.2 已列提纲，待细化）

### 市场人物追踪细化（待后续）
- key_persons.py 从 7 扩展到 15 人（P0）
- X 平台替代方案确定（RSSHub 自托管 vs 间接追踪）
- MCP Capitol Trades 集成测试

---

## 下一步建议

1. ✅ 红方复审 —— 已通过（1 条件，已修）
2. 用户审批最终方案
3. 开始 Phase 1-4 实现（数据层 + 配置 + 影子模块重构）
4. 日内交易研究写入最终方案
