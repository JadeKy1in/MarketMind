# Playground 候选调研（2026-09-29）

> 所有人要求：去外网找热门的投资 skills / 程序，评估能否放进 Playground（作为 agent 或数据源）。6 个只读调研 Agent 分 6 个方向（AI skills 市场、开源 LLM 交易框架、投资人思维框架蒸馏、量化因子与策略库、免费另类数据、加密智能体与信号）。本文是汇总；每条注明来源，推断另标。访问日期均为 2026-09-29。
>
> 评估口径（Playground 设计）：只用公开数据；能写成 manifest 自声明；能产出可结算的方向判断（标的、方向、持有期、确信度，止损由代码计算）；许可证允许个人使用；在利雅得网络可达；不依赖偷看未来的回测成绩。

## 1. 结论（推荐第一批）

| 类别 | 候选 | 为什么 | 接入方式 |
|---|---|---|---|
| 外部 agent 程序 | TradingAgents（Apache-2.0，约 10.9 万星，2026-09 仍在更新） | 最热门；按标的与日期给 5 档评级；可当库调用 | 独立虚拟环境子进程；需 Anthropic API 密钥或改用 DeepSeek 后端（它不走 Claude 命令行）；与自建辩论台直接对比 |
| 外部 agent 程序 | daily_stock_analysis（MIT，约 6.6 万星） | 覆盖 A/港/美，免费数据（AkShare / Baostock），支持 Claude / DeepSeek，给买卖评级、0–100 分与价位 | 命令行 dry-run 输出解析；止损改由代码计算 |
| 思维框架（自建，代码为主） | Minervini 趋势模板 + VCP | 规则可完全由代码计算，适合"几波大行情"；也是 LLM agent 必须跑赢的规则基准 | 代码筛选 + LLM 只写一句催化剂说明 |
| 思维框架（自建） | Druckenmiller 流动性 | 最贴合所有人画像：每年 2–4 次、看美联储资产负债表 − TGA − 逆回购、利率、美元、信用利差 | 代码做流动性面板（FRED 已接），LLM 只在流动性与趋势同向时出判断 |
| 加密（代码） | 链上估值 agent（Coin Metrics 免费 MVRV + alternative.me 恐惧贪婪） | 无需密钥、实测能取数；MVRV 有同行评审证据（样本只有约 3 个周期，偏弱） | BTC/ETH 多 / 空仓位区间，和趋势状态机、买入持有比 |
| 量化（代码） | 加密 1–4 周时间序列动量（波动率缩放，只做大币） | 同行评审证据最强（Liu & Tsyvinski, RFS 2021） | 复用 _quant 工具 |
| 数据源 | Coin Metrics、恐惧贪婪、BTC 现货 ETF 资金流（TFTC，CC BY 4.0）、SEC 交割失败数据、DefiLlama 扩展 | 免费、可回测或可存档、不重复 | 写成 Playground 数据源（manifest 可声明），也可供影子使用 |

需要所有人决定：外部程序（TradingAgents、daily_stock_analysis）各自要装一整套依赖（LangChain 等），按规则须先批准；建议放在独立虚拟环境里跑，不污染主环境。

## 2. 其他候选（第二批或不推荐）

- **AI skills**：UZI-Skill（MIT，66 个投资人人设给 0–100 分，无需密钥，数据全来自东方财富 / 雪球 / 新浪等中文源；其人设面板里已含 Serenity，与现有 agent 相关性高）；InvestSkill（MIT，输出格式最接近我们）；ai-berkshire（MIT，巴菲特 / 芒格 / 段永平 / 李录，只做多）；女娲人设 skills（芒格、巴菲特、段永平：只给思维框架，不给代码判断，需要包一层强制出判断）。anthropics/financial-services 依赖付费数据，不适合。
- **投资人框架**：CAN SLIM（代码可算大部分，但 O'Neil 自己的基金表现差）；Soros 反身性（适合加密与主题，规则模糊，易事后编故事）；冯柳"弱者体系"（逆向、赔率优先，可增加多样性）；Weinstein 阶段分析（SSRN 研究显示与简单均线过滤夏普相同 → 只作基准）；Marks 周期（作风险叠加层，不选股）。
- **量化**：52 周新高距离、月末效应（证据分歧，可能已衰减）、波动率管理叠加层（只做仓位层，样本外证据有争议）、Alpha158 特征喂给现有梯度提升 agent、DAA 金丝雀广度。跳过：FOMC 前漂移（2015 年后消失）、资金费率套利（需要空腿、据报已衰减）、Faber / 百年趋势（与现有重复）。
- **另类数据**：Indeed 招聘指数（CC-BY）、App Store 榜单（需自建存档）、Finnhub 分析师评级趋势（已有密钥）、Manifold（游戏币预测市场，替代被屏蔽的 Polymarket）、akshare（中国数据；新依赖，"仅供学术研究"，上游易变）。排除：Quiver（无免费 API）、Estimize（约 $1k/月）、WhaleWisdom / OpenInsider（条款禁止自动抓取）、Cboe 卖空量（2023 年起收费）、Metaculus（AI 使用需书面许可）。
- **加密智能体**：CryptoTrade（非商业许可、论文复现显示跑输买入持有）、Alpha Arena 实盘（6 个 LLM 中 4 个亏损）、Freqtrade 社区策略（5 分钟级、过拟合）、ElizaOS / aixbt（迷因币、利益冲突），都不推荐接入；Coinbase 溢价、资金费率极值只作特征。

## 3. 共同风险

- **只有回测、没有经过验证的实盘成绩**：所有仓库都声明"不构成投资建议"；星数不等于成绩。本系统只做前向纸面记账、按晋升阶梯判定，正好规避。
- **偷看未来 / 记忆**：LLM 读过这些投资人的名场面；ai-hedge-fund 在回测中隐藏代码与日期的做法值得借鉴。
- **提示词注入**：读社交媒体的程序（UZI-Skill、TradingAgents 的 Reddit / StockTwits）风险高，放在隔离环境、不给写权限。
- **网络**：部分程序默认用 yfinance / Yahoo；利雅得网络对 Yahoo 网页有屏蔽（行情接口本系统实测可用）。中文数据源从利雅得的可达性需实测。
- **Python 版本**：多数仓库要求 3.11–3.13，本机为 3.14 → 独立虚拟环境子进程。

## References（访问日期 2026-09-29）

- https://github.com/TauricResearch/TradingAgents ; https://arxiv.org/html/2412.20138
- https://github.com/ZhuLinsen/daily_stock_analysis
- https://github.com/virattt/ai-hedge-fund ; https://github.com/virattt/ai-hedge-fund/blob/main/ROADMAP.md
- https://github.com/wbh604/UZI-Skill ; https://github.com/yennanliu/InvestSkill ; https://github.com/xbtlin/ai-berkshire
- https://github.com/alchaincyf/nuwa-skill ; https://github.com/tmstack/awesome-persona-skills ; https://github.com/alchaincyf/munger-skill ; https://github.com/will2025btc/buffett-perspective ; https://github.com/derrickgong87/duan-yongping-skill ; https://github.com/leslieyeo/serenity-reply
- https://github.com/tradermonty/claude-trading-skills ; https://github.com/Chris-mian/claude-investment-skills ; https://github.com/anthropics/financial-services ; https://github.com/kangarooking/cangjie-skill
- https://github.com/HKUDS/Vibe-Trading ; https://github.com/AI4Finance-Foundation/FinGPT ; https://github.com/AI4Finance-Foundation/FinRobot ; https://github.com/ulab-uiuc/live-trade-bench ; https://github.com/ChenYXxxx/stockbench ; https://github.com/FinStep-AI/ContestTrade ; https://github.com/hsliuping/TradingAgents-CN
- https://arxiv.org/abs/2510.07920 （Profit Mirage）; https://arxiv.org/pdf/2510.11695 （Agent Market Arena）
- Minervini 趋势模板：https://deepvue.com/screener/minervini-trend-template/ ; CAN SLIM：https://en.wikipedia.org/wiki/CAN_SLIM ; Weinstein 研究：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7429238 ; Druckenmiller 讲话（第三方文字稿）：https://www.danielscrivner.com/stanley-druckenmiller-rare-lost-tree-club-lecture/ ; Soros：https://www.georgesoros.com/2014/01/13/fallibility-reflexivity-and-the-human-uncertainty-principle-2/ ; Marks 备忘录：https://www.oaktreecapital.com/insights/memo/the-best-of ; 冯柳：https://36kr.com/p/2202467165219976
- McLean & Pontiff：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2156623 ; Jensen, Kelly & Pedersen：https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249 ; Moreira & Muir：https://ideas.repec.org/a/bla/jfinan/v72y2017i4p1611-1644.html ; Liu & Tsyvinski：https://academic.oup.com/rfs/article-abstract/34/6/2689/5912024 ; George & Hwang：https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf ; 月末效应：https://quantpedia.com/strategies/turn-of-the-month-in-equity-indexes ; DAA：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3212862 ; Qlib Alpha158：https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/loader.py
- Coin Metrics：https://gitbook-docs.coinmetrics.io/packages/coin-metrics-community-data ; MVRV 研究：https://www.sciencedirect.com/science/article/pii/S0275531926002138 ; 恐惧贪婪：https://api.alternative.me/fng ; ETF 资金流：https://www.tftc.io/bitcoin-etf-flows ; BIS 加密套利：https://www.bis.org/publications/working-paper-1087-crypto-carry ; CryptoTrade 复现：https://arxiv.org/html/2410.12464v3
- 数据源：https://api-docs.defillama.com/ ; https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data ; https://github.com/hiring-lab/job_postings_tracker ; https://github.com/akfamily/akshare ; https://docs.manifold.markets/api ; https://finnhub.io/pricing
