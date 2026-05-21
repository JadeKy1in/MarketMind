# MarketMind v2.0

> AI-Powered Investment Analysis Workstation · Multi-Agent Shadow Ecosystem
> AI 驱动的投资分析工作站 · 多智能体影子生态系统

---

## What is MarketMind?

MarketMind is a personal AI investment analysis platform. Every morning, it collects global financial news, runs deep analysis through a multi-stage LLM pipeline, and presents structured investment decisions. Meanwhile, 24 independent AI "shadows" — each a virtual fund manager with their own personality, strategy, and data sources — compete internally, evolve their methodologies, and graduate to earn discussion rights at Gate 2.

**MarketMind does not trade for you.** It is an analysis and decision-support tool. You remain the final decision maker.

## 概览

MarketMind 是一个个人 AI 投资分析平台。每天早上收集全球财经新闻，通过多阶段 LLM 管道进行深度分析，输出结构化的投资决策。同时，24 个独立 AI「影子」——每个都是拥有自己策略、数据源和个性的虚拟基金经理——在内部竞争排名、进化方法论、毕业获得 Gate 2 对话资格。

**MarketMind 不替你交易。** 它是分析和决策支持工具。你始终是最终决策者。

---

## Quick Start · 快速开始

```bash
cd projects/marketmind

# Web Dashboard (recommended)
python api_server.py
# Open http://localhost:8520

# CLI daily analysis
python app.py --mode daily --mock --verbose

# GUI desktop app
python app.py --mode gui

# Inject external information before analysis
python app.py --mode daily --inject "Goldman says Q2 GDP revised" --inject-files report.pdf chart.png
```

Double-click `start.bat` to launch the dashboard with one click.

双击 `start.bat` 一键启动仪表盘。

---

## Architecture · 架构

```
marketmind/
├── api_server.py          # FastAPI + embedded dashboard · 内嵌仪表盘
├── dashboard.html         # Bloomberg-style Apple-typography web UI
├── app.py                 # CLI/GUI entry point · 入口
├── start.bat              # One-click launcher · 一键启动
│
├── gateway/               # LLM gateway + 10 data fetchers · 网关与数据
│   ├── async_client.py    # DeepSeek Flash/Pro + circuit breaker
│   ├── fred_client.py     # FRED API: 32 macro series · 宏观序列
│   ├── sentiment_fetcher.py  # CBOE, CNN, AAII · 情绪数据
│   ├── commodity_fetcher.py  # LME, USDA, EIA, World Bank · 大宗商品
│   ├── crypto_onchain.py  # DeFiLlama, Blockchain.com · 链上数据
│   ├── vol_surface_fetcher.py  # VIX futures, SKEW · 波动率曲面
│   ├── vol_global_fetcher.py   # VVIX, VSTOXX · 全球波动率
│   ├── world_bank_fetcher.py   # Pink Sheet · 商品价格
│   ├── reliable_api.py    # Timeout + retry · 可靠调用
│   └── multimodal_adapter.py  # Gemini Flash OCR · 多模态
│
├── pipeline/              # Main AI: 10-stage analysis · 主管道
│   ├── scout.py           # 35 sources · 新闻采集
│   ├── flash_triage.py    # Flash LLM signal sorting · 信号分诊
│   ├── investigation_loop.py  # HVR deep-dive · 深度调查
│   ├── layer1_narrative.py    # Narrative · 叙事层
│   ├── layer2_fundamental.py  # Fundamental · 基本面
│   ├── layer3_technical.py    # Technical · 技术面
│   ├── red_team.py        # Adversarial review · 红方审查
│   ├── decision.py        # Decision + NoTrade card · 决策合成
│   ├── gate1/2/3_interaction.py  # Three human gates · 三重关卡
│   ├── info_injector.py   # External info · 信息注入
│   ├── figure_signal.py   # 16 tracked persons · 市场人物
│   ├── awa_scorer.py      # Ability × Willingness × Acknowledgment
│   ├── event_study_runner.py  # Statistical validation · 事件研究
│   ├── methodology_rules.py   # SHARP: rule decomposition · 规则分解
│   ├── methodology_attribution.py  # Flash LLM hypothesis · 归因
│   └── methodology_evolution.py   # WFA gate + atomic edits · 进化
│
├── shadows/               # 24-shadow ecosystem · 影子生态 (50+ modules)
│   ├── shadow_mother.py   # Orchestration · 调度中心 (286 lines)
│   ├── shadow_state.py    # SQLite persistence · 持久化 (333 lines)
│   ├── expert_shadows.py  # 16 domain experts · 领域专家
│   ├── momentum_shadows.py    # 4 trend followers · 趋势跟随
│   ├── contrarian_shadows.py  # 4 "Daredevil" · 敢死队
│   ├── ranking_engine.py  # Composite scoring · 复合排名
│   ├── walk_forward.py    # Overfitting detection · 过拟合检测
│   ├── challenger_engine.py   # 3-stage elimination · 淘汰机制
│   ├── graduation_engine.py   # Tier 1/2 + stress tests · 毕业
│   ├── post_graduation_monitor.py  # CUSUM/CUSUMSQ · 毕业后监控
│   ├── consensus_extractor.py  # Cross-shadow aggregation · 共识
│   ├── diversity_controller.py # Crowding warning · 集中度
│   ├── dpp_selector.py    # Quality-diversity · DPP 选择
│   └── ... (40+ modules)  · 40+ 模块
│
├── config/                # Configuration · 配置
├── storage/               # FTS5 archive + gate logs · 归档
├── integrity/             # Prompt sanitizer + watchdog · 安全
├── ui/                    # Desktop GUI (customtkinter) · 桌面界面
├── tests/                 # 1,744 tests · 测试
└── data/                  # Runtime SQLite databases · 运行时数据
```

---

## The 24 Shadows · 24 影子

Shadows are independent AI fund managers. They compete, evolve, and graduate — but never vote on your decisions.

影子是独立 AI 基金经理。它们竞争、进化、毕业——但不参与你的决策投票。

| Type · 类型 | Count | Description · 描述 |
|------|:-----:|------|
| Expert · 专家 | 16 | Gold, Crypto, Oil, Bonds, Vol, EM, Tech, Financials, Healthcare, Consumer, Industrials, Metals, Agriculture, REITs, FX, Macro · 黄金/加密/石油/债券/波动率/新兴市场/科技/金融/医疗/消费/工业/金属/农业/地产/外汇/宏观 |
| Momentum · 动量 | 4 | Intraday, Weekly Trend, Event Hound, Sector Rotation · 日内/周线/事件/板块轮动 |
| Contrarian · 逆向 | 4 | Fade Master, Sideways Scout, Vol Surfer, Crash Hunter · 共识逆向/区间猎手/恐慌冲浪/泡沫猎手 |

**Self-Evolution · 自进化**: 6 layers — ranking → challenger → knowledge inheritance → diversity → crystallization → ecosystem simulation.

**Graduation · 毕业**: Tier 1 (competence) → Tier 2 (excellence) → Stress Tests (GFC 2008 / COVID 2020 / Rate Hikes 2022) → Gate 2 participation.

---

## Information Sources · 信息源

| Source · 来源 | Data · 数据 | Cost · 成本 |
|--------|------|:----:|
| FRED API | 32 macro series · 宏观序列 | Free |
| CBOE | Put/Call, VIX futures · 期权数据 | Free |
| DefiLlama | DeFi TVL, DEX volume · 链上 TVL | Free |
| Blockchain.com | BTC hashrate · 哈希率 | Free |
| Alternative.me | Crypto Fear & Greed · 加密情绪 | Free |
| CFTC COT | Futures positioning · 期货持仓 | Free |
| World Bank | Commodity prices · 商品价格 | Free |
| EIA | Oil/gas inventory · 能源库存 | Free |
| BLS | CPI, employment · 通胀就业 | Free |
| SEC EDGAR | Corporate filings · 公司财报 | Free |
| FDA openFDA | Drug approvals · 药品审批 | Free |
| Gemini Flash | Image/PDF OCR · 多模态识别 | Free tier |

---

## Dashboard · 仪表盘

Launch `python api_server.py` and open `http://localhost:8520`.

- **Bloomberg dark theme** + Apple PingFang typography
- **Progress bar**: compact, always visible · 进度条常驻
- **Chat**: primary interaction area with file attachment · 聊天主交互区
- **Portfolio**: collapsible sidebar, quick glance · 持仓侧边栏
- **Shadow overlay**: full detail on click, collapses when done · 影子详情浮层
- **Decision card**: auto-displayed with gold border · 决策卡片自动展示
- **14 timezone support** with localStorage persistence · 14 时区可选
- **Bilingual** English/Chinese throughout · 全界面中英双语

---

## PICA Audit · 审计状态

| Level | Status · 状态 |
|-------|:----:|
| PICA-Unit | 1,744 pass · 通过 |
| PICA-Security | 39 files, 0 findings · 零发现 |
| PICA-Integration | Import DAG verified · 导入验证 |
| PICA-Regression | Zero regressions · 零回归 |
| Red Team Code | 37 files audited · 已审计 |
| Red Team Logic | 1 critical fix applied · 已修复 |

---

## Requirements · 依赖

```bash
pip install fastapi uvicorn httpx yfinance scipy numpy scikit-learn openpyxl
pip install customtkinter  # for GUI mode
```

## Environment · 环境变量

| Variable | Purpose · 用途 |
|----------|---------|
| `DEEPSEEK_API_KEY` | DeepSeek API key (required) |
| `FRED_KEY` | FRED macro data · 宏观数据 |
| `EIA_KEY` | EIA energy data · 能源数据 |
| `GEMINI_API_KEY` | Gemini Flash OCR · 多模态 |
| `NEWSAPI_KEY` | NewsAPI (optional) |
| `GNEWS_API_KEY` | GNews (optional) |
| `FALLBACK_API_KEY` | Fallback LLM provider · 备用 LLM |

---

## Session History · 会话历史

| Date | Commit | Summary · 摘要 |
|------|--------|---------|
| 2026-05-22 | `e416239e` | Bilingual Apple-style dashboard v2 · 仪表盘 |
| 2026-05-21 | `c7f1a4bb` | Dashboard v1 + orchestration compliance |
| 2026-05-21 | `2e59d6b` | Phase E/F + Market Figure Module · 人物模块 |
| 2026-05-21 | `fa21c769` | Modular extraction + Phase B/C/D · 模块化 |
| 2026-05-21 | `ac1f3cff` | RESTART GUIDE 6/6 complete · 全部完成 |

---

**MarketMind v2.0** — Built with DeepSeek, audited by Claude, owned by you.
