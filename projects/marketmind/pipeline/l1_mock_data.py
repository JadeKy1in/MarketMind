"""L1 Interactive — mock data objects for testing without API calls.

Data-only module — no behavioral code. Extracted from layer1_interactive.py.
"""
from __future__ import annotations

# ── Mock responses for testing (no API calls) ───────────────────────────────

MOCK_DEEP_ANALYSIS = """## Deep Analysis

### 1. Dominant Narrative
The dominant market narrative is "Fed patience meets tech earnings momentum." The Fed's steady-rate signal reduces near-term policy uncertainty, while strong tech earnings confirm AI-driven demand is real and accelerating. However, rising oil prices on Middle East concerns introduce a stagflationary risk that competes with the soft-landing narrative.

### 2. Causal Chain
- **Fed holds steady** → reduces rate volatility → supports growth equity valuations → favors tech/consumer discretionary
- **Oil price surge** → increases input costs → compresses margins in transport/manufacturing → potential inflation resurgence → could delay future rate cuts
- **Tech earnings beat** → confirms AI CapEx cycle is durable → semiconductor demand sustained → positive for SOXX/SMH
- **ECB rate cut hint** → weakens EUR → strengthens USD → creates headwind for commodities and EM
- **China export beat** → signals global demand resilience → positive for industrial metals and shipping

### 3. Directional Scenarios (evidence-based, no numeric probabilities)
- **Dominant scenario (strongest signal support)**: Tech earnings + Fed patience → risk-on for growth equities. Evidence: CNBC Fed signal (strong), Yahoo Tech earnings (strong).
- **Alternative scenario (if key assumption wrong)**: Oil supply disruption persists → stagflationary pressure → growth/value rotation. Evidence: Bloomberg oil surge (moderate), SCMP China export (moderate).
- **Tail risk**: Middle East escalation widens beyond current scope → broad risk-off. Evidence: BBC geopolitical fragment (weak signal).
- Trigger conditions and evidence strength listed per scenario. No numeric probabilities assigned.

### 4. Information Gaps
- Missing: Oil inventory data (API/EIA this week)
- Missing: Fed minutes detail on inflation tolerance
- Missing: Tech earnings guidance (not just results)
- Missing: China credit impulse data for March

### 5. Confidence Calibration
- Fed narrative: 0.75 confidence
- Oil impact: 0.60 confidence (dependent on geopolitical developments)
- Tech earnings durability: 0.70 confidence
- China export signal: 0.55 confidence (one-month data point)

=== CONCISE ===

**投资方向**：偏多科技和消贵，但对油价上行保持警惕。

**关键理由**（最多3条）：
1. 美联储按兵不动 + 科技财报超预期 → AI 资本支出周期确定性增强 [高置信度]
2. 中东供应担忧推高油价 → 如果持续突破$90将压缩下游利润 [中等置信度]
3. 中国出口超预期 + ECB 降息暗示 → 全球需求韧性好于市场定价 [中等置信度]

**信息缺口**（需要核实的事项）：
- 本周 API/EIA 原油库存数据
- 美联储会议纪要中的通胀容忍度表述
- 科技公司全年 Capex 指引（不仅是上季度结果）

**风险提示**：油价若突破$95将逆转当前的软着陆叙事，触发成长股轮动卖出。

**提问**：你认为油价上涨是短期波动还是结构性趋势？这会直接影响我们今天是否加仓能源板块。"""

MOCK_DISCUSSION_RESPONSE = """[中等置信度] 关于油价问题，当前数据更支持"短期供应冲击"而非结构性趋势。

**支持短期判断的证据**：
1. 中东供应中断历史上持续时间中位数是 45 天（过去 20 年 12 次事件）
2. OPEC+ 仍有 300 万桶/日的闲置产能可以释放
3. 全球 SPR 库存处于 5 年均值附近，有释放空间

**但如果出现以下情况，我会转向结构性判断**：
1. 霍尔木兹海峡通行受阻（概率低但影响极大）
2. OPEC+ 明确不增产（目前没有信号）
3. 美国页岩油产量见顶（EIA 月度数据需跟踪）

**我的建议**：今天不加仓能源。先等本周 EIA 库存数据，如果库存下降超预期且油价站稳$90以上，明天再考虑。

你还有其他担心吗？或者我们可以进入 L2 做标的筛选了？"""

MOCK_MINING_RESPONSE = """[数据挖掘结果]

按你的要求搜索了"中东石油供应中断历史"相关数据：

**历史模式**：
- 过去 20 年中东供应中断 12 次，恢复时间中位数 45 天
- 单次事件 Brent 平均涨幅 12%，但 3 个月内回吐 80% 涨幅
- 只有 2 次演变为结构性牛市（2008、2022）

**当前特殊性**：
- 本次事件涉及的生产设施占全球供应 2%，低于历史均值 4%
- 但红海航运保险费率已上涨 300%，反映市场定价了更高风险

**结论**：历史模式不支持油价持续 >$95，但航运中断可能持续更久。维持"短期冲击"判断。"""

# ── Mock tool responses for testing (no API calls) ─────────────────────────

MOCK_FUNDAMENTALS_AAPL = {
    "source": "yfinance",
    "info": {
        "trailingPE": 32.5, "forwardPE": 28.1, "marketCap": 3500000000000,
        "sector": "Technology", "industry": "Consumer Electronics",
        "revenueGrowth": 0.05, "debtToEquity": 1.62, "returnOnEquity": 1.45,
        "regularMarketPrice": 195.0, "fiftyTwoWeekHigh": 220.0, "fiftyTwoWeekLow": 165.0,
    },
}

MOCK_NEWS_SEARCH_RESULTS = [
    {"title": "Oil inventories drop unexpectedly — EIA report", "source": "Reuters", "publishedAt": "2026-05-15T10:00:00Z"},
    {"title": "OPEC+ considers output increase amid supply concerns", "source": "Bloomberg", "publishedAt": "2026-05-15T09:30:00Z"},
    {"title": "Oil demand growth slows in China — bearish signal for crude", "source": "SCMP", "publishedAt": "2026-05-15T08:00:00Z"},
]

MOCK_ELITE_OPINIONS = {
    "domain": "energy",
    "opinions": [
        {"shadow_name": "energy_hawk", "opinion": "Oil supply disruption is likely short-term. OPEC+ spare capacity at 3M bbl/day provides ample buffer.", "confidence": 0.75},
        {"shadow_name": "macro_bear", "opinion": "Energy sector is overbought on geopolitical premium. Fundamentals don't support $90+ Brent.", "confidence": 0.65},
    ],
}

