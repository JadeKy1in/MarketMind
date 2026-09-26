"""Shadow metadata — Chinese names, role descriptions, domain labels."""
from __future__ import annotations

# shadow_id → {cn_name, desc, domain_cn}
# Generated from live shadow configs (2026-05-27), 25 shadows.
SHADOW_META: dict[str, dict[str, str]] = {
    # ── Expert Shadows (16) ──────────────────────────────────────────
    "expert:gold:bullion_broker": {
        "cn_name": "黄金经纪人",
        "desc": "实际利率·央行购金·COT持仓·ETF流量·实物溢价",
        "domain_cn": "贵金属",
        "method_bilingual": "分析实际利率、美元、央行购金、COT持仓、ETF流量和实物溢价来评估贵金属 / Analyze real rates, USD, central bank buying, COT positioning, ETF flows & physical premiums for precious metals",
    },
    "expert:crypto:chain_oracle": {
        "cn_name": "链上先知",
        "desc": "链上指标·哈希率·稳定币流量·DeFi TVL·监管动向",
        "domain_cn": "加密货币",
        "method_bilingual": "分析链上指标(哈希率/活跃地址)、稳定币流量、DeFi TVL和监管动向 / Analyze on-chain metrics, stablecoin flows, DeFi TVL & regulatory signals for crypto",
    },
    "expert:energy:oil_geologist": {
        "cn_name": "石油地质师",
        "desc": "OPEC+决策·原油库存·钻井数·地缘供应风险",
        "domain_cn": "能源",
        "method_bilingual": "分析OPEC+决策、原油库存、钻井数和地缘政治供应风险来评估能源市场 / Analyze OPEC+ decisions, crude inventories, rig counts & geopolitical supply risks for energy",
    },
    "expert:bonds:yield_whisperer": {
        "cn_name": "收益率耳语者",
        "desc": "收益率曲线·期限利差·TIPS盈亏平衡·央行前瞻指引",
        "domain_cn": "固定收益",
        "method_bilingual": "分析收益率曲线形状、期限利差、TIPS盈亏平衡和央行前瞻指引 / Analyze yield curve shape, term spreads, TIPS breakevens & central bank forward guidance for fixed income",
    },
    "expert:vol:vega_trader": {
        "cn_name": "Vega交易员",
        "desc": "VIX期限结构·波动率曲面·skew·尾部对冲成本",
        "domain_cn": "波动率",
        "method_bilingual": "分析VIX期限结构(contango/backwardation)、波动率曲面偏斜和尾部风险对冲成本 / Analyze VIX term structure, vol surface skew & tail hedge costs for volatility",
    },
    "expert:em:frontier_scout": {
        "cn_name": "前沿侦察兵",
        "desc": "美元强弱·EM利差·资本流动·政治风险·外汇储备",
        "domain_cn": "新兴市场",
        "method_bilingual": "分析美元走势、新兴市场债券利差、资本流动和政治风险 / Analyze DXY, EM bond spreads, capital flows & political risk for emerging markets",
    },
    "expert:tech:silicon_oracle": {
        "cn_name": "硅谷先知",
        "desc": "盈利动量·半导体周期·AI capex·云计算·芯片供应链",
        "domain_cn": "科技",
        "method_bilingual": "分析盈利动量、半导体周期、AI资本支出和云计算增长来评估科技板块 / Analyze earnings momentum, semiconductor cycles, AI capex & cloud growth for tech sector",
    },
    "expert:financials:bank_examiner": {
        "cn_name": "银行审查官",
        "desc": "收益率曲线陡峭度·净息差·贷款损失准备·资本充足率",
        "domain_cn": "金融",
        "method_bilingual": "分析收益率曲线陡峭度对银行净息差的影响、贷款损失准备和资本充足率 / Analyze yield curve steepness impact on NIM, loan loss reserves & capital ratios for financials",
    },
    "expert:healthcare:trial_reviewer": {
        "cn_name": "临床试验审查员",
        "desc": "FDA审批日历·临床试验数据·专利悬崖·医保政策",
        "domain_cn": "医疗",
        "method_bilingual": "分析FDA审批日历、临床试验数据、专利到期和医保政策 / Analyze FDA approval calendars, clinical trial data, patent cliffs & healthcare policy",
    },
    "expert:consumer:wallet_watcher": {
        "cn_name": "钱包观察者",
        "desc": "零售趋势·消费者信心·信用卡数据·库存周期",
        "domain_cn": "消费",
        "method_bilingual": "分析零售趋势、消费者信心、信用卡支出数据和库存周期 / Analyze retail trends, consumer confidence, credit card data & inventory cycles for consumer sector",
    },
    "expert:industrials:factory_floor": {
        "cn_name": "工厂车间主任",
        "desc": "PMI(ISM/全球)·新订单·资本品·运输指数·基建支出",
        "domain_cn": "工业",
        "method_bilingual": "分析全球PMI、新订单、资本品需求和运输指数来评估工业板块 / Analyze global PMI, new orders, capital goods & transportation indices for industrials",
    },
    "expert:macro:cycle_reader": {
        "cn_name": "周期解读师",
        "desc": "增长-通胀平衡·美联储路径·跨资产相关性·流动性",
        "domain_cn": "宏观",
        "method_bilingual": "分析增长-通胀平衡、美联储政策路径和跨资产相关性来评估宏观环境 / Analyze growth-inflation balance, Fed policy path & cross-asset correlations for macro",
    },
    "expert:metals:steel_trader": {
        "cn_name": "钢铁交易员",
        "desc": "中国需求·房地产开工·基建支出·全球PMI·库存",
        "domain_cn": "工业金属",
        "method_bilingual": "分析中国需求指标、房地产开工、基建支出和全球PMI来评估工业金属 / Analyze China demand, housing starts, infrastructure spending & global PMI for industrial metals",
    },
    "expert:realestate:reit_analyst": {
        "cn_name": "REIT分析师",
        "desc": "利率·出租率·Cap Rate·房地产信贷·REIT估值",
        "domain_cn": "房地产",
        "method_bilingual": "分析利率、出租率、资本化率和房地产信贷状况来评估REIT / Analyze interest rates, occupancy, cap rates & real estate credit for REITs",
    },
    "expert:fx:currency_dealer": {
        "cn_name": "外汇交易员",
        "desc": "利差·央行干预·经常账户·套息交易·地缘风险",
        "domain_cn": "外汇",
        "method_bilingual": "分析利差、央行干预、经常账户和套息交易流向 / Analyze rate differentials, central bank intervention, current accounts & carry trade flows for FX",
    },
    "expert:short:bear_tracker": {
        "cn_name": "空头追踪者",
        "desc": "做空信号·估值泡沫·会计红旗·负面催化剂·拥挤交易",
        "domain_cn": "做空策略",
        "method_bilingual": "全领域扫描做空目标：法务会计分析、空头持仓、put/call比率、内幕卖出信号 / Cross-domain short specialist: forensic accounting, short interest, put/call ratios, insider selling patterns",
    },

    # ── Daredevil Shadows (8, grouped by domain) ──────────────────────
    # Domain: 横盘(range_bound) + 动量(momentum) — 原"动量"组
    "daredevil:range_bound:sideways_scout": {
        "cn_name": "侧翼侦察兵",
        "desc": "横盘市场(VIX<20)·期权卖方·区间交易·均值回归",
        "domain_cn": "横盘",
        "method_bilingual": "在低波动横盘市场中寻找区间交易机会，卖出期权获取时间价值 / Sell options & trade ranges in low-VIX sideways markets",
    },
    "daredevil:momentum:trend_chaser": {
        "cn_name": "趋势追逐者",
        "desc": "趋势市场(ADX>25)·突破交易·ETF动量轮动",
        "domain_cn": "动量",
        "method_bilingual": "识别并追踪强趋势，利用ADX和价格动量进行突破交易 / Chase strong trends using ADX & price momentum for breakout trades",
    },
    # Domain: 逆向(contrarian) + 恐慌(panic) — 原"敢死队"组
    "daredevil:contrarian:herd_fader": {
        "cn_name": "羊群逆行者",
        "desc": "情绪极端(共识>80%)·逆向抄底·恐慌买入",
        "domain_cn": "逆向",
        "method_bilingual": "在共识极端时逆势操作，检测市场情绪极值进行逆向布局 / Fade extreme consensus, buy when herd panics",
    },
    "daredevil:panic:vol_surfer": {
        "cn_name": "波动冲浪者",
        "desc": "恐慌市场(VIX>30)·VXX对冲·尾部风险·崩盘后恢复",
        "domain_cn": "恐慌",
        "method_bilingual": "在VIX>30恐慌环境中交易波动率产品，对冲尾部风险 / Trade vol products in panic regimes, hedge tail risk",
    },
    # Domain: short + leveraged — 原"敢死队"高风险组
    "daredevil:crash:hunter": {
        "cn_name": "崩盘猎手",
        "desc": "崩盘预警·过度杠杆·流动性危机·系统性风险指标",
        "domain_cn": "做空",
        "method_bilingual": "检测系统性风险信号，在市场崩盘前建立空头头寸 / Detect systemic risk, short before crashes",
    },
    "daredevil:leveraged:lever_hunter": {
        "cn_name": "杠杆猎手",
        "desc": "杠杆ETF(TQQQ/SQQQ/SOXL)·波动衰减·再平衡风险",
        "domain_cn": "杠杆",
        "method_bilingual": "交易杠杆ETF，管理波动衰减和再平衡风险 / Trade leveraged ETFs, manage volatility decay & rebalancing risk",
    },
    # Domain: low_liq + sector — 特种环境组
    "daredevil:low_liq:depth_diver": {
        "cn_name": "深潜者",
        "desc": "低流动性市场·宽买卖价差·小盘股·场外交易",
        "domain_cn": "低流动性",
        "method_bilingual": "在低流动性环境中寻找深度价值，管理买卖价差和流动性风险 / Hunt deep value in illiquid markets, manage bid-ask spreads",
    },
    "daredevil:sector:sector_spinner": {
        "cn_name": "板块旋转器",
        "desc": "板块轮动·相对强度·行业ETF·经济周期映射",
        "domain_cn": "板块轮动",
        "method_bilingual": "追踪板块轮动，利用相对强度和经济周期在各行业ETF间切换 / Track sector rotation, rotate across sector ETFs by relative strength",
    },

    # ── Catfish — REPLACED by ecosystem_auditor.py (mechanism, not shadow) ──
    "catfish:primary:minority_enforcer": {
        "cn_name": "鲶鱼少数派 [已退役]",
        "desc": "已被EcosystemAuditor取代——不再作为影子运行。盲点扫描机制替代了共识质疑功能。",
        "domain_cn": "退役",
    },
}


def get_shadow_meta(shadow_id: str) -> dict[str, str]:
    """Return {cn_name, desc, domain_cn} for a shadow.

    Falls back to extracting from shadow_id format if not in registry:
    "type:domain:role" → cn_name=role (humanized)
    """
    if shadow_id in SHADOW_META:
        return dict(SHADOW_META[shadow_id])

    # Auto-generate from shadow_id: "type:domain:role_name"
    parts = shadow_id.split(":")
    if len(parts) >= 3:
        role = parts[-1].replace("_", " ").title()
        domain = parts[1].replace("_", " ").title()
        return {
            "cn_name": role,
            "desc": f"{domain}分析 · {parts[0].title()} Strategy",
            "domain_cn": domain,
        }

    return {
        "cn_name": shadow_id,
        "desc": "策略分析 · Strategy Analysis",
        "domain_cn": "",
    }
