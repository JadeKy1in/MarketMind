# MarketMind · 市场心智

> AI 驱动的投资信号验证与决策支持系统  
> AI-Powered Investment Signal Validation & Decision Support

25 个独立 AI 影子并行分析市场信号，投票、排名、淘汰，形成投资决策。支持真实/模拟 API。  
25 independent AI shadows analyze market signals in parallel — vote, rank, eliminate — producing investment decisions. Real & mock API modes.

**[→ 项目代码 / Source](projects/marketmind/)** | **1,998 tests · 0 fail · 0 skip**

---

## 架构 / Architecture

```
28 新闻源 / News Sources → Scout → Flash Triage → L1 叙事评级 (A-E)
    ↓
L2 基本面 + L3 技术面 (并行 / parallel)
    ↓
25-Shadow Ecosystem (16 Experts + 8 Daredevils + 1 Catfish)
    ├── 独立分析 → 投票 → 排名 → 结晶化 / Independent Analysis → Vote → Rank → Crystallize
    ├── 3 阶段挑战者淘汰 / 3-stage Challenger Elimination (t-test + Calmar gate)
    └── 串通检测 + 紧急配额审计 / Collusion Detection + Emergency Quota Audit
    ↓
Red Team 对抗 + Resonance 验证 → Decision 决策 → Archive 归档
```

**实时监控 / Real-time**: WebSocket → Dashboard（状态灯、影子排名、阶段进度 / status, rankings, stage progress）

---

## 快速开始 / Quick Start

```bash
cd projects/marketmind

# 启动 Dashboard → http://localhost:8520
python api_server.py

# 模拟分析（不消耗 API）/ mock mode (no API cost)
python app.py --mode daily --mock -v

# 真实 API 分析 / live API
python app.py --mode daily -v

# 运行测试 / run tests
python -m pytest tests/ -v -m "not slow" -p no:warnings
```

---

## 技术栈 / Tech Stack

| 层 / Layer | 技术 / Technology |
|-----------|-------------------|
| AI 推理 | DeepSeek Flash (轻量 / light) + DeepSeek Pro (深度 / deep) |
| 后端 / Backend | Python 3.11+, FastAPI + Uvicorn, WebSocket |
| 前端 / Frontend | 原生 HTML/CSS/JS Dashboard |
| 数据 / Data | SQLite (WAL), 28 个 RSS/JSON API 新闻源 |
| 统计 / Stats | SciPy, NumPy, scikit-learn |
| CI/CD | GitHub Actions（push 自动测试 / auto-test on push） |

---

## 影子生态系统 / Shadow Ecosystem

25 个 AI 代理，各自拥有独立方法论、风险偏好和领域专长。  
25 AI agents, each with independent methodology, risk profile, and domain expertise.

**16 专家影子 / Experts**: 领域专精（黄金、加密货币、能源、债券、波动率等）  
**8 冒险者影子 / Daredevils**: 高风险策略（动量、均值回归、突破、反转）  
**1 鲶鱼影子 / Catfish**: 反共识——所有人一致时发出警告  

**排名 / Ranking**: 每日复合评分（MPPM + Sharpe + Calmar + Omega + 胜率），Walk-Forward Efficiency 防过拟合。  
**淘汰 / Elimination**: 3 阶段——警告 → 秘密挑战者 → 配对比较（t-test + Calmar 门控）。  
**ELITE 资格**: 顶级表现者获得额外配额和更高投票权重。

---

## 测试 / Tests

```
1,998 passed, 0 failed, 0 skipped
├── Pipeline:    1,019  (Scout, Flash, L1-L3, Red Team, Resonance, Decision)
├── Shadows:       492  (Agent, Ranking, Challenger, Crystallization, Memory)
├── API:            16  (Routes, WebSocket, Data Providers)
├── 实盘干跑:        5  (9 阶段全管线真实 LLM，CI 跳过)
└── 其他:          466  (Storage, Config, Gateway, UI, Tools)
```

---

## 开发门禁 / Development Gates

| 门禁 / Gate | 何时 / When | 作用 / What |
|------------|------------|------------|
| **PreToolUse** | 编辑 .py 前 | 需声明任务 (`current_task.json`) |
| **Pre-commit** | 提交前 | 每文件 500 行上限 |
| **Stop Gate** | 会话结束 | 7 项 PICA 审计 |
| **CI** | Push 时 | GitHub Actions 自动全量测试 |

---

## 项目结构 / Project Structure

```
projects/marketmind/
├── pipeline/          # 10 阶段分析管线
│   ├── scout.py               # 28 源新闻采集
│   ├── layer1_narrative.py    # L1 事件评级 + 矩阵
│   ├── layer2_fundamental.py  # L2 基本面分析
│   ├── layer3_technical.py    # L3 技术面分析
│   ├── red_team.py            # 对抗挑战
│   ├── resonance.py           # 统计验证
│   └── decision.py            # 决策合成
├── shadows/          # 25 影子生态系统
│   ├── shadow_mother.py       # 每日编排
│   ├── ranking_engine.py      # 复合评分
│   └── challenger_engine.py   # 3 阶段淘汰
├── api/              # FastAPI 服务
│   ├── routes.py              # REST 端点
│   └── websocket.py           # 实时推送
├── gateway/          # LLM 路由
│   └── async_client.py        # DeepSeek Flash/Pro
├── config/           # 配置
├── storage/          # 归档（JSON + SQLite FTS5）
├── tests/            # 1,998 项测试
└── data/             # 运行时数据（按日期组织）
```

---

## 配置 / Setup

复制 `.env.example` 为 `.env`：
```bash
DEEPSEEK_API_KEY=your_key
NEWSAPI_KEY=your_key       # 可选
GNEWS_API_KEY=your_key     # 可选
```
