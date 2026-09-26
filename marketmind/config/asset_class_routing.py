"""Asset-class routing taxonomy for causal and flow decomposition modules.
Phase H v2.1 — expanded from 5 to 9 classes (Red Team C1/C2 fix).
Routes hypotheses to the appropriate decomposition lens based on asset class,
preventing the universal balance-sheet lens problem (Logic C1/C2).

9 classes: US_FIXED_INCOME, US_EQUITIES, EUROPEAN_EQUITIES, JAPANESE_EQUITIES,
EM_MACRO, COMMODITIES, FX_MAJORS, FX_EM, CRYPTO
"""

from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class AssetClassConfig:
    class_id: str
    name: str                          # Chinese + English
    decomposition_lens: str            # which decomposition method to apply
    entity_types: list[str]            # entities specific to this asset class
    net_directional_force: str         # what "direction" means for this class
    keywords: list[str]                # Chinese + English keywords for routing
    tickers: list[str]                 # representative tickers
    key_data_sources: list[str]        # FRED codes, APIs


ASSET_CLASSES: dict[str, AssetClassConfig] = {
    "US_FIXED_INCOME": AssetClassConfig(
        class_id="US_FIXED_INCOME",
        name="美国固定收益 / US Fixed Income",
        decomposition_lens="balance_sheet",
        entity_types=["US_HOUSEHOLD", "US_INSTITUTIONAL", "FOREIGN_OFFICIAL",
                       "FOREIGN_PRIVATE", "FED"],
        net_directional_force="net_liquidity_impact",
        keywords=["Treasury", "美债", "国债", "TIPS", "MBS", "agency", "SOFR", "Fed",
                  "美联储", "FOMC", "利率", "降息", "加息", "量化", "QE", "QT", "缩表",
                  "扩表", "收益率", "yield", "duration", "久期"],
        tickers=["TLT", "IEF", "SHY", "AGG", "MBB", "LQD", "HYG"],
        key_data_sources=["FRED:WALCL", "FRED:RRPONTSYD", "FRED:WTREGEN",
                          "FRED:WRBWFRBL", "FRED:DGS10", "FRED:DGS2"]
    ),
    "US_EQUITIES": AssetClassConfig(
        class_id="US_EQUITIES",
        name="美国股票 / US Equities",
        decomposition_lens="earnings_discount_rate",
        entity_types=["RETAIL_INVESTOR", "INSTITUTIONAL", "CORPORATE_BUYBACK",
                       "FOREIGN_INVESTOR", "HEDGE_FUND"],
        net_directional_force="net_flow_pressure",
        keywords=["S&P", "Nasdaq", "美股", "标普", "科技股", "AI", "earnings", "估值",
                  "板块", "sector", "大盘", "小盘", "growth", "value", "回购",
                  "buyback", "dividend", "SPY", "QQQ", "VTI", "Magnificent 7"],
        tickers=["SPY", "QQQ", "IWM", "DIA", "VTI"],
        key_data_sources=["FRED:SP500", "market_data:SPY", "FRED:GS10",
                          "FRED:T10Y2Y", "FRED:VIXCLS"]
    ),
    "EUROPEAN_EQUITIES": AssetClassConfig(
        class_id="EUROPEAN_EQUITIES",
        name="欧洲股票 / European Equities",
        decomposition_lens="ecb_policy_earnings",
        entity_types=["ECB", "EU_INSTITUTIONAL", "EXPORT_SECTOR",
                       "GLOBAL_ALLOCATOR", "HEDGE_FUND"],
        net_directional_force="net_flow_pressure",
        keywords=["欧洲", "欧股", "ECB", "欧元区", "EU", "Stoxx", "DAX", "FTSE",
                  "CAC", "eurozone", "欧元", "EUR", "european", "欧盟", "欧洲央行",
                  "EU fiscal", "欧盟财政", "Stoxx 600", "泛欧", "Schatz", "Bund",
                  "拉加德", "Lagarde", "PMI euro", "德国", "法国"],
        tickers=["EZU", "VGK", "FEZ", "IEUR"],
        key_data_sources=["ECB:refi_rate", "FRED:EFFR", "market_data:VGK",
                          "Eurostat:PMI", "FRED:DELEXUSEU"]
    ),
    "JAPANESE_EQUITIES": AssetClassConfig(
        class_id="JAPANESE_EQUITIES",
        name="日本股票 / Japanese Equities",
        decomposition_lens="boj_gpif_carry",
        entity_types=["BOJ", "GPIF", "JAPANESE_RETAIL", "FOREIGN_HEDGE_FUND",
                       "JAPANESE_CORPORATE"],
        net_directional_force="net_flow_pressure",
        keywords=["日本", "日股", "日経", "Nikkei", "BoJ", "日銀", "日本银行",
                  "GPIF", "yen", "日元", "円", "JPX", "TOPIX", "Tokyo", "东京",
                  "日本央行", "carry", "套息", "植田", "Ueda", "corporate governance",
                  "公司治理", "JPY", "ETF購入", "ETF购入", "JGB", "国債", "日本国债",
                  "TPX", "JP225"],
        tickers=["EWJ", "DXJ", "BBJP", "JPXN"],
        key_data_sources=["BOJ:policy_rate", "FRED:DEXJPUS", "market_data:EWJ",
                          "Nikkei225", "MoF:flow_data"]
    ),
    "EM_MACRO": AssetClassConfig(
        class_id="EM_MACRO",
        name="新兴市场宏观 / EM Macro",
        decomposition_lens="dollar_cycle_capital_flow",
        entity_types=["SOVEREIGN_ISSUER", "IMF", "EM_CENTRAL_BANK",
                       "GLOBAL_EM_FUND", "LOCAL_INSTITUTIONAL"],
        net_directional_force="net_capital_flow_pressure",
        keywords=["新兴市场", "EM", "emerging market", "EEM", "VWO", "EMBI",
                  "capital flows", "资金流", "DXY", "美元", "sovereign", "主权",
                  "IMF", "国际货币基金", "EM FX", "新兴货币", "carry trade", "套息交易",
                  "China credit", "中国信贷", "EPFR", "credit impulse", "前沿市场",
                  "frontier", "de-dollarization", "去美元化", "EM debt", "新兴债",
                  "sovereign spread"],
        tickers=["EEM", "VWO", "EMB", "PCY"],
        key_data_sources=["JP:EMBI_spread", "FRED:DTWEXBGS", "EPFR:em_flows",
                          "BIS:global_liquidity", "IIF:capital_flows"]
    ),
    "COMMODITIES": AssetClassConfig(
        class_id="COMMODITIES",
        name="大宗商品 / Commodities",
        decomposition_lens="supply_demand_inventory",
        entity_types=["PRODUCER", "CONSUMER", "SPECULATOR", "EXCHANGE_INVENTORY",
                       "SOVEREIGN_RESERVE"],
        net_directional_force="net_supply_demand_balance",
        keywords=["原油", "黄金", "铜", "大豆", "天然气", "crude", "oil", "gold",
                  "copper", "soybean", "natgas", "commodity", "大宗", "OPEC", "页岩",
                  "shale", "供应", "需求", "库存", "inventory", "backwardation",
                  "contango", "WTI", "Brent", "布伦特", "贵金属", "precious metal",
                  "铁矿石", "iron ore", "agriculture", "农产品", "小麦", "wheat",
                  "玉米", "corn", "grain", "粮食", "咖啡", "coffee", "糖", "sugar",
                  "棉花", "cotton", "农业", "livestock", "fertilizer", "cocoa"],
        tickers=["GLD", "USO", "UNG", "DBA", "CPER", "SLV", "PPLT",
                 "CORN", "WEAT", "SOYB"],
        key_data_sources=["EIA:inventory", "CFTC:COT", "FRED:CPILFESL",
                          "market_data:GLD"]
    ),
    "FX_MAJORS": AssetClassConfig(
        class_id="FX_MAJORS",
        name="G10外汇 / FX Majors",
        decomposition_lens="dual_central_bank_carry",
        entity_types=["CENTRAL_BANK_A", "CENTRAL_BANK_B", "CARRY_TRADER",
                       "CORPORATE_HEDGER", "SOVEREIGN_FUND"],
        net_directional_force="net_carry_pressure",
        keywords=["EUR/USD", "USD/JPY", "GBP/USD", "USD/CHF", "AUD/USD",
                  "NZD/USD", "USD/CAD", "DXY", "美元指数", "G10", "major",
                  "主要货币", "forex", "外汇", "利差", "carry", "央行", "central bank",
                  "CIP", "covered interest parity", "cross-currency basis",
                  "swap line", "G7", "Dollar", "欧元兑美元", "英镑", "sterling",
                  "cable", "Aussie", "Kiwi", "Loonie"],
        tickers=["UUP", "FXY", "FXE", "FXB", "FXA", "FXC"],
        key_data_sources=["FRED:DEXJPUS", "FRED:DEXUSEU", "FRED:DTWEXBGS",
                          "CFTC:COT_FX", "BIS:triennial"]
    ),
    "FX_EM": AssetClassConfig(
        class_id="FX_EM",
        name="新兴市场外汇 / FX EM",
        decomposition_lens="capital_controls_carry_reserve",
        entity_types=["EM_CENTRAL_BANK", "CARRY_TRADER", "IMF",
                       "SOVEREIGN_WEALTH_FUND", "SPECULATOR"],
        net_directional_force="net_em_fx_pressure",
        keywords=["EM FX", "新兴货币", "USD/TRY", "USD/ZAR", "USD/BRL", "USD/MXN",
                  "USD/INR", "capital control", "资本管制", "IMF program", "IMF计划",
                  "reserve adequacy", "外汇储备", "EM carry", "新兴套息", "frontier",
                  "前沿市场", "sovereign default", "主权违约", "devaluation", "贬值",
                  "currency crisis", "货币危机", "lira", "real", "rand", "rupiah",
                  "peso", "NDF"],
        tickers=["CEW", "EMLC", "LEMB", "BZF"],
        key_data_sources=["FRED:DTWEXBGS", "IMF:IFS_reserves", "BIS:locational",
                          "EPFR:em_fx_flows", "JPM:EMCI"]
    ),
    "CRYPTO": AssetClassConfig(
        class_id="CRYPTO",
        name="加密货币 / Crypto",
        decomposition_lens="onchain_offchain",
        entity_types=["EXCHANGE_RESERVE", "MINER", "ETF_ISSUER",
                       "STABLECOIN_ISSUER", "RETAIL_HODLER"],
        net_directional_force="net_accumulation_pressure",
        keywords=["BTC", "ETH", "比特币", "以太坊", "加密货币", "blockchain", "DeFi",
                  "stablecoin", "稳定币", "挖矿", "mining", "hash", "哈希", "ETF",
                  "custody", "托管"],
        tickers=["BTC-USD", "ETH-USD"],
        key_data_sources=["crypto:exchange_reserves", "crypto:hash_rate",
                          "market_data:BTC-USD"]
    ),
}


def route_asset_class(
    text: str,
    tickers: list[str] | None = None
) -> tuple["AssetClassConfig | None", float]:
    """Route a hypothesis to the appropriate asset class based on keywords and tickers.

    Returns (AssetClassConfig, confidence) where confidence is normalized 0-1.
    Returns (None, 0.0) if no class can be determined or confidence < 0.3.

    Strategy: ticker match first (confidence 0.95), then keyword density.
    Disambiguation: if two classes score within 0.1, logs warning and picks higher.
    """
    if not text:
        return None, 0.0

    text_lower = text.lower()

    # Phase 1: ticker match (highest confidence)
    if tickers:
        ticker_set = {t.upper() for t in tickers}
        for config in ASSET_CLASSES.values():
            if ticker_set & {t.upper() for t in config.tickers}:
                return config, 0.95

    # Phase 2: keyword density with confidence scoring
    scores: list[tuple["AssetClassConfig", float]] = []
    for config in ASSET_CLASSES.values():
        match_count = sum(1 for kw in config.keywords if kw.lower() in text_lower)
        if match_count > 0:
            confidence = min(match_count / 5.0, 0.9)
            scores.append((config, confidence))

    if not scores:
        return None, 0.0

    scores.sort(key=lambda x: x[1], reverse=True)
    best_config, best_confidence = scores[0]

    # Disambiguation: warn if runner-up is within 0.1
    if len(scores) >= 2:
        runner_config, runner_confidence = scores[1]
        if abs(best_confidence - runner_confidence) <= 0.1:
            logger.warning(
                f"Asset class disambiguation: '{best_config.class_id}' "
                f"({best_confidence:.2f}) vs '{runner_config.class_id}' "
                f"({runner_confidence:.2f}) — picking {best_config.class_id}"
            )

    if best_confidence < 0.3:
        return None, 0.0

    return best_config, best_confidence


__all__ = ["AssetClassConfig", "ASSET_CLASSES", "route_asset_class"]
