"""Institutional mechanism glossary for prompt enrichment.
Maps mechanism names to descriptions, data sources, and directional implications.
Phase H v2 — addresses the "needs precise terminology" gap.
"""

MECHANISM_GLOSSARY: dict[str, dict] = {
    # ── Federal Reserve tools ──
    "eSLR": {
        "name_zh": "补充杠杆率豁免",
        "description": "Supplemental Leverage Ratio exemption — reduces the extra leverage buffer for large banks, freeing balance sheet capacity for Treasury/MBS purchases.",
        "data_source": "Fed regulatory announcements",
        "directional": "宽松 → 利多风险资产（银行购债能力上升）",
        "related": ["SLR", "GSIB_surcharge", "CCAR"]
    },
    "IORB": {
        "name_zh": "准备金余额利率",
        "description": "Interest on Reserve Balances — the rate the Fed pays banks on reserves. The floor of the fed funds rate corridor.",
        "data_source": "FRED: IORB",
        "directional": "IORB > EFFR → 资金倾向留在准备金（抽水）; EFFR > IORB → 资金倾向流向短债（放水）",
        "related": ["EFFR", "ON_RRP", "SOFR"]
    },
    "ON_RRP": {
        "name_zh": "隔夜逆回购",
        "description": "Overnight Reverse Repo — money market funds park cash at the Fed overnight. ON RRP falling = cash leaving the facility into markets (liquidity positive).",
        "data_source": "FRED: RRPONTSYD",
        "directional": "ON RRP↓ → 流动性进入市场（利多风险资产）; ON RRP→0 → 最后流动性缓冲耗尽",
        "related": ["IORB", "SOFR", "TGA"]
    },
    "TGA": {
        "name_zh": "财政部一般账户",
        "description": "Treasury General Account — the US government's checking account at the Fed. TGA rising = Treasury pulling cash from the banking system (liquidity drain).",
        "data_source": "FRED: WTREGEN",
        "directional": "TGA↑ → 银行准备金↓（抽水）; TGA↓ → 银行准备金↑（放水）",
        "related": ["bank_reserves", "debt_ceiling", "ON_RRP"]
    },
    "FIMA_repo": {
        "name_zh": "FIMA回购便利",
        "description": "Foreign and International Monetary Authorities repo facility — allows foreign central banks to repo Treasuries for USD without selling them outright. Prevents forced Treasury selling during USD shortages.",
        "data_source": "Fed H.4.1 Table 1a",
        "directional": "FIMA使用↑ → 外国央行缺美元（压力信号）; 常态化 → 系统性兜底",
        "related": ["dollar_swap_lines", "FX_swap", "TIC_data"]
    },
    "SOFR": {
        "name_zh": "担保隔夜融资利率",
        "description": "Secured Overnight Financing Rate — the broad Treasury repo market rate. Replaced LIBOR. SOFR-IORB spread is a key liquidity stress indicator.",
        "data_source": "FRED: SOFR",
        "directional": "SOFR-IORB利差扩大 → 回购市场压力; >25bp → 2019年9月式流动性危机信号",
        "related": ["IORB", "repo", "dealers"]
    },
    "EFFR": {
        "name_zh": "有效联邦基金利率",
        "description": "Effective Federal Funds Rate — the actual rate banks charge each other for overnight loans. Should trade within the Fed's target range.",
        "data_source": "FRED: EFFR",
        "directional": "EFFR突破利率走廊上限 → 准备金不足 → 流动性危机",
        "related": ["IORB", "SOFR", "bank_reserves"]
    },
    "bank_reserves": {
        "name_zh": "银行准备金",
        "description": "Bank reserves held at the Fed — the raw material of the financial system. Determines repo market functioning and overall liquidity conditions.",
        "data_source": "FRED: WRBWFRBL",
        "directional": "准备金连续下降 → 回购利率上行压力; 跌破2.7T → 系统性流动性风险",
        "related": ["SOFR", "IORB", "TGA", "ON_RRP"]
    },
    # ── Market mechanisms ──
    "FX_swap": {
        "name_zh": "外汇掉期",
        "description": "FX swap — one party borrows currency A and lends currency B against collateral. Used by Japanese/European institutions to fund USD asset purchases. Size is in trillions.",
        "data_source": "BIS Triennial Survey; cross-currency basis from Bloomberg/FRED",
        "directional": "FX swap基差扩大 → 美元融资压力; 日本/欧洲机构减持美债风险",
        "related": ["cross_currency_basis", "basis_trade", "carry_trade"]
    },
    "basis_trade": {
        "name_zh": "基差套利",
        "description": "Hedge fund strategy: long cash Treasuries + short Treasury futures, leveraged 50-100x. Profits from convergence of cash and futures prices. Dominant player in long-end Treasury liquidity.",
        "data_source": "CFTC COT (leveraged funds positioning); CME futures open interest",
        "directional": "避险爆发 → 期货暴涨 → 对冲基金被迫平仓 → 现货暴跌 → 螺旋踩踏",
        "related": ["FX_swap", "Treasury_futures", "hedge_funds"]
    },
    "yield_curve_steepening": {
        "name_zh": "收益率曲线陡峭化",
        "description": "Yield curve steepening — short-end rates fall (Fed cuts) while long-end rates rise (inflation/fiscal premium). Punishes growth stocks (high duration) and favors value/cyclical.",
        "data_source": "FRED: T10Y2Y, T10Y3M",
        "directional": "陡峭化 → 成长股承压（折现率上升）、银行股利多（净息差扩大）",
        "related": ["duration", "growth_vs_value", "bank_stocks"]
    },
    "volatility_suppression": {
        "name_zh": "波动率镇压",
        "description": "Large funds selling VIX futures/options to keep implied vol artificially low, creating a window for asset distribution. Historically precedes sharp vol expansions.",
        "data_source": "CBOE VIX term structure; VIX futures CFTC COT",
        "directional": "VIX被压制在15以下 → 资金派发窗口; VIX突然回归 → 市场暴跌",
        "related": ["VIX", "put_call_ratio", "tail_risk"]
    },
    "dealer_balance_sheet": {
        "name_zh": "交易商资产负债表",
        "description": "Primary dealer balance sheet capacity — dealers intermediate Treasury auctions and repo. When balance sheets are full, Treasury auctions fail and repo rates spike.",
        "data_source": "Fed H.4.1; FRED primary dealer statistics",
        "directional": "交易商库存高 → 承接能力下降 → 国债拍卖尾部风险上升",
        "related": ["repo", "Treasury_auction_cycle", "SOFR"]
    },
    "Treasury_auction_cycle": {
        "name_zh": "国债拍卖周期",
        "description": "Quarterly refunding and weekly auction schedule that drives dealer positioning, repo rate fluctuations, and yield movements around auction dates.",
        "data_source": "TreasuryDirect auction calendar",
        "directional": "拍卖前 → 交易商做空对冲 → 收益率上行; 拍卖后 → 回补 → 收益率下行",
        "related": ["dealer_balance_sheet", "repo", "yield_curve"]
    },
    "term_premium": {
        "name_zh": "期限溢价",
        "description": "Term premium — the extra yield investors demand for holding long-duration bonds. Decomposed from 10Y yield by ACM model. Negative term premium = Fed QE distortion.",
        "data_source": "FRED: THREEFYTP10 (ACM estimate)",
        "directional": "期限溢价上行 → 市场担心财政/通胀 → 长端收益率上升; 期限溢价负值 → QE压制",
        "related": ["yield_curve", "QE", "duration", "us10y_4.5pct"]
    },
    "credit_spread": {
        "name_zh": "信用利差",
        "description": "Credit spread — the yield premium of corporate bonds over Treasuries. Widening = credit stress, tightening = risk-on. IG (LQD) and HY (HYG) spreads tracked separately.",
        "data_source": "FRED: BAMLC0A0CM, BAMLH0A0HYM2",
        "directional": "利差扩大 → 信用市场压力 → 股市承压; 利差收窄 → 风险偏好上升",
        "related": ["CDS_basis", "IG_vs_HY", "volatility_suppression"]
    },
    "CDS_basis": {
        "name_zh": "CDS基差",
        "description": "CDS basis — the spread between CDS premiums and bond-implied credit spreads. Negative basis = CDS cheaper than bonds (bond market overpricing risk).",
        "data_source": "Bloomberg CDS monitor; ICE Clear Credit",
        "directional": "负基差扩大 → 债市低估信用风险 → 信用事件爆发时CDS暴涨",
        "related": ["credit_spread", "bond_liquidity", "counterparty_risk"]
    },
    "VIX_term_structure": {
        "name_zh": "VIX期限结构",
        "description": "VIX futures term structure — contango (front < back) = calm markets; backwardation (front > back) = near-term fear exceeds long-term. Backwardation is a reliable crisis signal.",
        "data_source": "CBOE VIX futures; VIXCentral",
        "directional": "升水 → 市场平静; 贴水 → 恐慌集中在近期 → 系统性风险上升",
        "related": ["VIX", "volatility_suppression", "put_call_ratio"]
    },
    "put_call_ratio": {
        "name_zh": "看跌/看涨比率",
        "description": "Put/Call ratio — options market sentiment gauge. Elevated PCR = excessive hedging/fear (often contrarian bullish). Very low PCR = complacency (bearish).",
        "data_source": "CBOE total/equity put-call ratios",
        "directional": "PCR极端高 → 恐慌见底（反向看涨）; PCR极端低 → 自满见顶（反向看跌）",
        "related": ["VIX", "VIX_term_structure", "volatility_suppression"]
    },
    "margin_debt": {
        "name_zh": "保证金债务",
        "description": "FINRA margin debt — total borrowed money to buy stocks. Rising = leverage building, bullish but fragile. Falling sharply = forced deleveraging.",
        "data_source": "FINRA margin statistics (monthly)",
        "directional": "保证金债务快速上升 → 杠杆积累 → 回调时踩踏风险; 急速下降 → 去杠杆恐慌",
        "related": ["retail_investor", "volatility_suppression", "ETF_flow"]
    },
    "ETF_flow": {
        "name_zh": "ETF资金流",
        "description": "ETF creation/redemption flows — tracks institutional demand for major equity/bond ETFs. Persistent outflows signal distribution; persistent inflows signal accumulation.",
        "data_source": "ETF.com fund flows; Bloomberg ETF flow monitor",
        "directional": "持续净流入 → 机构积累; 持续净流出 → 机构派发; 收益率上升+资金流入 → 抄底资金",
        "related": ["dark_pool_volume", "margin_debt", "retail_investor"]
    },
    "dark_pool_volume": {
        "name_zh": "暗池交易量",
        "description": "Dark pool volume as a percentage of total equity volume — institutional off-exchange trading. Rising = institutions selling without moving markets (distribution signal).",
        "data_source": "FINRA ATS statistics; SIFMA",
        "directional": "暗池占比上升 → 机构在暗处出货/进货; 公开市场上涨+暗池占比上升 → 派发",
        "related": ["ETF_flow", "institutional_investor", "retail_investor"]
    },
    # ── International mechanisms ──
    "dollar_swap_lines": {
        "name_zh": "美元互换额度",
        "description": "Fed dollar swap lines with ECB/BoJ/BoE/SNB — provides USD to foreign central banks during global dollar shortages. Prevents forced fire sales of US assets by foreign institutions.",
        "data_source": "Fed H.4.1 Table 1a (central bank liquidity swaps)",
        "directional": "互换额度使用↑ → 全球美元短缺（避险信号）",
        "related": ["FIMA_repo", "FX_swap", "global_dollar_shortage"]
    },
    "cross_currency_basis": {
        "name_zh": "交叉货币基差",
        "description": "Cross-currency basis — the premium/discount for swapping one currency into another. Negative USD basis = it costs more to borrow USD, indicating dollar funding stress.",
        "data_source": "Bloomberg CCB function; FRED: EXJPUS, EXUSEU (proxy)",
        "directional": "负基差扩大 → 美元融资紧张 → 外国机构被迫抛售美债/美股",
        "related": ["FX_swap", "dollar_swap_lines", "carry_trade"]
    },
    "TIC_data": {
        "name_zh": "国际资本流动报告",
        "description": "Treasury International Capital — monthly/quarterly data on cross-border portfolio flows into/out of US securities. The authoritative source on who is buying/selling US assets.",
        "data_source": "Treasury.gov TIC SLT (monthly, ~6-week lag)",
        "directional": "外国官方减持 → 地缘政治信号; 开曼群岛增持 → 对冲基金活跃",
        "related": ["FIMA_repo", "balance_of_payments", "FX_reserves"]
    },
    "carry_trade": {
        "name_zh": "套息交易",
        "description": "Borrow in low-yield currency (JPY, CHF) to invest in high-yield assets. Trillions in size. Unwinds violently when funding currency appreciates — the 'yen carry' crash pattern.",
        "data_source": "CFTC COT (non-commercial JPY/CHF positioning); BIS",
        "directional": "日元升值 → 套息交易平仓 → 全球风险资产承压; 利差扩大 → 套息交易再起",
        "related": ["FX_swap", "cross_currency_basis", "dollar_swap_lines"]
    },
    # ── Key thresholds ──
    "bank_reserves_2.7T": {
        "name_zh": "银行准备金2.7万亿警戒线",
        "description": "The level of US bank reserves (~$2.7T) below which repo rates historically spike above IORB, indicating reserve scarcity and systemic liquidity stress.",
        "data_source": "FRED: WRBWFRBL",
        "directional": "跌破2.7万亿 → SOFR飙升 → 回购市场冻结 → 广泛资产下跌",
        "related": ["SOFR", "IORB", "repo", "ON_RRP"]
    },
    "us10y_4.5pct": {
        "name_zh": "10年期美债4.5%关键位",
        "description": "The 10-year Treasury yield level (~4.5%) that has repeatedly triggered policy reversals (tariff concessions, Fed dovish pivots) since 2024. Acts as a political pain threshold.",
        "data_source": "FRED: DGS10",
        "directional": "突破4.5% → 政策急转弯（利好风险资产）; 保持在4.5%以下 → 现状维持",
        "related": ["yield_curve", "tariff_policy", "fiscal_deficit"]
    },
}

MECHANISM_ESCAPE_HATCH = (
    "\n\nIMPORTANT: If you encounter a financial mechanism, facility, or tool that you "
    "cannot confirm the exact operational details of, state explicitly: "
    "'我无法确认该机制的具体运作方式' (I cannot confirm the exact operational details "
    "of this mechanism). Do NOT guess, extrapolate, or fabricate mechanism details. "
    "It is better to acknowledge uncertainty than to produce plausible-sounding but incorrect analysis."
)

__all__ = ["MECHANISM_GLOSSARY", "MECHANISM_ESCAPE_HATCH"]
