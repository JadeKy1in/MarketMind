"""Tests for Fabrication Watchdog M1-M4."""
import pytest
from projects.marketmind.integrity.watchdog import (
    NumericClaim, AgentIntegrityScore, inject_m1_protocol,
    extract_claims_m2, update_score_m4, evaluate_strikes,
    STRIKE_CONSEQUENCES, M2_PATTERNS,
)


def test_inject_m1_protocol_prepends():
    result = inject_m1_protocol("Analyze markets.", "test-agent")
    assert "DATA_INTEGRITY_PROTOCOL" in result
    assert "test-agent" in result
    assert "Analyze markets." in result
    assert result.index("DATA_INTEGRITY_PROTOCOL") < result.index("Analyze markets.")


def test_extract_claims_price():
    claims = extract_claims_m2("SPY is currently at $520.50 with a 15.3% gain this month.", "builder", "sess-1")
    prices = [c for c in claims if c.claim_type == "price"]
    percentages = [c for c in claims if c.claim_type == "percentage"]
    assert len(prices) >= 1
    assert len(percentages) >= 1
    assert any("520.50" in p.value for p in prices)
    assert any("15.3" in p.value for p in percentages)


def test_extract_claims_date():
    claims = extract_claims_m2("Report published on 2026-05-11 shows earnings growth.", "builder", "sess-1")
    dates = [c for c in claims if c.claim_type == "date"]
    assert len(dates) >= 1
    assert dates[0].value == "2026-05-11"


def test_extract_claims_ratio():
    claims = extract_claims_m2("The Sharpe ratio of 2.5 and P/E ratio 25.0 indicate strong performance.", "builder", "sess-1")
    ratios = [c for c in claims if c.claim_type == "ratio"]
    assert len(ratios) >= 1


def test_extract_claims_amount_comma():
    """AF-2: Comma-separated thousands must be captured correctly."""
    claims = extract_claims_m2("Market cap reached 1,234 billion USD with revenue of 345.7 million.", "builder", "sess-1")
    amounts = [c for c in claims if c.claim_type == "amount"]
    assert len(amounts) >= 2
    values = [a.value for a in amounts]
    assert "1234" in values, f"Expected '1234' in {values} — comma-separated thousands not stripped"
    assert any("345" in v for v in values), f"Expected '345.7' or similar in {values}"


def test_extract_claims_no_numbers():
    claims = extract_claims_m2("No numeric data here, just qualitative analysis.", "builder", "sess-1")
    assert claims == []


def test_update_score_verified_true():
    score = AgentIntegrityScore(agent_id="test")
    claim = NumericClaim(value="520.50", claim_type="price", context="SPY price",
                         source_agent="test", session_id="s1", timestamp="2026-01-01",
                         verified=True, verification_source="yfinance/SPY",
                         ground_truth="520.50")
    score = update_score_m4(score, claim)
    assert score.score == 100
    assert score.verified_true == 1
    assert score.total_claims == 1


def test_update_score_verified_false():
    score = AgentIntegrityScore(agent_id="test")
    claim = NumericClaim(value="999", claim_type="price", context="SPY price",
                         source_agent="test", session_id="s1", timestamp="2026-01-01",
                         verified=False, verification_source="yfinance/SPY",
                         ground_truth="520.50")
    score = update_score_m4(score, claim)
    assert score.score == 85
    assert score.verified_false == 1
    assert score.strikes == 1


def test_evaluate_strikes():
    score = AgentIntegrityScore(agent_id="bad-agent")
    score.strikes = 3
    assert "TERMINATED" in evaluate_strikes(score)

    score2 = AgentIntegrityScore(agent_id="clean-agent")
    assert "No active penalty" in evaluate_strikes(score2)


def test_m2_patterns_coverage():
    assert "price" in M2_PATTERNS
    assert "ratio" in M2_PATTERNS
    assert "percentage" in M2_PATTERNS
    assert "date" in M2_PATTERNS
    assert "amount" in M2_PATTERNS
    for pattern in M2_PATTERNS.values():
        assert isinstance(pattern, str)


def test_normalize_value_strips_commas():
    claims = extract_claims_m2("Price: $1,234,567.89", "test", "s1")
    prices = [c for c in claims if c.claim_type == "price"]
    assert len(prices) >= 1
    assert prices[0].value == "1234567.89"


@pytest.mark.asyncio
async def test_verify_price_m3_sets_none_on_no_ticker():
    from projects.marketmind.integrity.watchdog import verify_claim_m3
    claim = NumericClaim(value="1234", claim_type="price", context="mystery asset at $1234",
                         source_agent="test", session_id="s1", timestamp="2026-01-01")
    result = await verify_claim_m3(claim)
    assert result.verification_source == "UNVERIFIABLE_FORWARD"


@pytest.mark.asyncio
async def test_verify_ratio_m3_sets_unverifiable_on_no_ticker():
    from projects.marketmind.integrity.watchdog import verify_claim_m3
    claim = NumericClaim(value="25.0", claim_type="ratio", context="Unknown P/E ratio 25.0",
                         source_agent="test", session_id="s1", timestamp="2026-01-01")
    result = await verify_claim_m3(claim)
    assert result.verification_source == "UNVERIFIABLE_FORWARD"
