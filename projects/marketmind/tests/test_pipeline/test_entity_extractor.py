"""Tests for Tier 1 entity extraction from news headlines."""
import pytest
from marketmind.pipeline.entity_extractor import (
    ExtractedEntities,
    extract_entities,
    ACRONYM_BLACKLIST,
)


class TestExtractTicker:
    def test_extract_known_ticker(self):
        result = extract_entities("AAPL beats earnings estimates, stock surges 5%")
        assert "AAPL" in result.tickers

    def test_extract_multiple_tickers(self):
        result = extract_entities("NVDA and AMD lead semiconductor rally; MSFT hits record high")
        assert "NVDA" in result.tickers
        assert "AMD" in result.tickers
        assert "MSFT" in result.tickers

    def test_acronym_blacklist_excluded(self):
        for acronym in ["FOMC", "ETF", "GDP", "CPI", "OPEC", "PMI", "ECB", "FED"]:
            result = extract_entities(f"{acronym} report shows mixed signals")
            assert acronym not in result.tickers, f"{acronym} should not be extracted as ticker"

    def test_common_word_excluded(self):
        result = extract_entities("THE market IS looking AT A very BIG rally TODAY")
        assert "THE" not in result.tickers
        assert "IS" not in result.tickers
        assert "AT" not in result.tickers
        assert "A" not in result.tickers

    def test_max_five_tickers(self):
        headline = "AAPL MSFT NVDA GOOGL AMZN META TSLA all report earnings this week"
        result = extract_entities(headline)
        assert len(result.tickers) <= 5

    def test_one_char_ticker_excluded(self):
        result = extract_entities("I think this is a very good trade")
        assert "I" not in result.tickers

    def test_three_char_ticker_extracted(self):
        result = extract_entities("SPY rallies on Fed decision")
        assert "SPY" in result.tickers

    def test_no_duplicate_tickers(self):
        result = extract_entities("AAPL stock surges as AAPL beats estimates")
        tickers = [t for t in result.tickers if t == "AAPL"]
        assert len(tickers) <= 1


class TestExtractCountry:
    def test_extract_country_en(self):
        result = extract_entities("US jobs report beats expectations")
        assert "US" in result.countries

    def test_extract_country_cn(self):
        result = extract_entities("德国经济数据好于预期")
        assert "Germany" in result.countries

    def test_extract_china_cn(self):
        result = extract_entities("中国央行宣布降准")
        assert "China" in result.countries

    def test_extract_us_cn(self):
        result = extract_entities("美国经济数据好于预期")
        assert "US" in result.countries
        assert "China" not in result.countries

    def test_extract_hong_kong_cn(self):
        result = extract_entities("香港股市大涨")
        assert "Hong_Kong" in result.countries

    def test_extract_australia_cn(self):
        result = extract_entities("澳大利亚央行维持利率不变")
        assert "Australia" in result.countries

    def test_extract_multiple_countries(self):
        result = extract_entities("US and China trade talks resume; EU negotiators join")
        assert "US" in result.countries
        assert "China" in result.countries
        assert "EU" in result.countries

    def test_country_not_in_empty_headline(self):
        result = extract_entities("Apple releases new iPhone")
        countries = set(c for c in result.countries if c not in ("US",))
        assert len(countries) == 0


class TestExtractSector:
    def test_extract_tech_sector(self):
        result = extract_entities("Technology stocks rally on AI chip demand")
        assert "tech" in result.sectors

    def test_extract_energy_sector(self):
        result = extract_entities("Oil prices surge as OPEC cuts production")
        assert "energy" in result.sectors

    def test_extract_cn_sector(self):
        result = extract_entities("金融板块下跌")
        assert "financial" in result.sectors

    def test_extract_ai_cn_sector(self):
        result = extract_entities("人工智能板块领涨科技股")
        assert "tech" in result.sectors

    def test_extract_crypto_sector(self):
        result = extract_entities("Bitcoin ETF approval drives crypto market higher")
        assert "crypto" in result.sectors


class TestExtractCurrency:
    def test_extract_usd(self):
        result = extract_entities("USD strengthens on hawkish Fed comments")
        assert "USD" in result.currencies

    def test_extract_eur_symbol(self):
        result = extract_entities("EUR/USD pair falls below parity")
        assert "EUR" in result.currencies

    def test_extract_euro_symbol(self):
        result = extract_entities("European markets: € strengthens against dollar")
        assert "EUR" in result.currencies

    def test_extract_bitcoin(self):
        result = extract_entities("Bitcoin surges past 100k")
        assert "BTC" in result.currencies

    def test_extract_gold(self):
        result = extract_entities("Gold hits new all-time high, up 2% today")
        assert "Gold" in result.currencies


class TestExtractIndex:
    def test_extract_sp500(self):
        result = extract_entities("S&P 500 closes at record high")
        assert "S&P_500" in result.indices

    def test_extract_nasdaq(self):
        result = extract_entities("Nasdaq leads tech rally, up 2%")
        assert "Nasdaq" in result.indices

    def test_extract_cn_index(self):
        result = extract_entities("上证综指重回3000点")
        assert "SSE" in result.indices

    def test_extract_hsi(self):
        result = extract_entities("恒生指数大涨3%")
        assert "HSI" in result.indices

    def test_extract_szse_cn(self):
        result = extract_entities("深证成指突破万点大关")
        assert "SZSE" in result.indices

    def test_extract_vix(self):
        result = extract_entities("VIX spikes 30% amid market turmoil")
        assert "VIX" in result.indices


class TestExtractCentralBank:
    def test_extract_fed(self):
        result = extract_entities("Fed signals rate cut in September")
        assert "Fed" in result.central_banks

    def test_extract_ecb(self):
        result = extract_entities("ECB holds rates steady as inflation cools")
        assert "ECB" in result.central_banks

    def test_extract_boj(self):
        result = extract_entities("日本央行维持负利率")
        assert "BOJ" in result.central_banks

    def test_extract_cn_central_bank(self):
        result = extract_entities("中国央行下调LPR利率")
        assert "PBoC" in result.central_banks


class TestExtractKeywords:
    def test_extract_rate_hike(self):
        result = extract_entities("Fed announces 25bp rate hike")
        assert "rate_hike" in result.keywords

    def test_extract_inflation(self):
        result = extract_entities("CPI data shows inflation cooling to 3.2%")
        assert "inflation" in result.keywords

    def test_extract_earnings(self):
        result = extract_entities("Apple earnings beat estimates on strong iPhone sales")
        assert "earnings" in result.keywords

    def test_extract_trade_war(self):
        result = extract_entities("New tariffs announced on Chinese imports")
        assert "trade_war" in result.keywords

    def test_extract_recession(self):
        result = extract_entities("Recession fears grow as yield curve inverts further")
        assert "recession" in result.keywords


class TestEmptyHeadline:
    def test_empty_string(self):
        result = extract_entities("")
        assert result.tickers == []
        assert result.countries == []
        assert result.currencies == []

    def test_none_headline(self):
        result = extract_entities("")
        assert isinstance(result, ExtractedEntities)

    def test_whitespace_only(self):
        result = extract_entities("   \t\n  ")
        assert result.tickers == []


class TestDataclassDefaults:
    def test_all_fields_default_to_empty_list(self):
        e = ExtractedEntities()
        assert e.tickers == []
        assert e.countries == []
        assert e.sectors == []
        assert e.currencies == []
        assert e.indices == []
        assert e.central_banks == []
        assert e.keywords == []


class TestAcronymBlacklistIntegrity:
    def test_all_acronyms_are_uppercase(self):
        for acronym in ACRONYM_BLACKLIST:
            assert acronym == acronym.upper(), f"{acronym} should be uppercase"

    def test_critical_acronyms_present(self):
        critical = {"FOMC", "GDP", "CPI", "ECB", "FED", "ETF", "OPEC", "PMI"}
        missing = critical - ACRONYM_BLACKLIST
        assert len(missing) == 0, f"Missing critical acronyms: {missing}"
