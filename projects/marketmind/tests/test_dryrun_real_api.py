"""Real-API dry run — stage-by-stage verification with actual API keys."""
import pytest
import asyncio
import time


@pytest.fixture(scope="function", autouse=True)
def _init_gateway():
    """Initialize DeepSeek gateway and reset circuit breaker before each test.

    Uses function scope so each test starts with a fresh circuit breaker,
    preventing cascade failures when network/proxy is unstable.
    """
    from marketmind.config.settings import MarketMindConfig
    from marketmind.gateway.async_client import init_gateway, get_gateway
    config = MarketMindConfig.from_env()
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)
    g = get_gateway()
    if hasattr(g, 'circuit_breaker') and g.circuit_breaker:
        g.circuit_breaker.reset()


@pytest.mark.slow
@pytest.mark.asyncio
async def test_stage1_scout_real():
    """Stage 1: Scout — fetch from 28 real news sources."""
    from marketmind.config.settings import MarketMindConfig
    from marketmind.pipeline.scout import fetch_all_sources

    config = MarketMindConfig.from_env()
    t0 = time.time()
    items = await fetch_all_sources(config, use_cross_run_cache=False)
    elapsed = time.time() - t0

    assert len(items) > 50, f"Expected >50 articles, got {len(items)} in {elapsed:.1f}s"
    assert all(item.title for item in items), "All items must have titles"
    assert all(item.source_name for item in items), "All items must have source_name"
    print(f"PASS: {len(items)} articles in {elapsed:.1f}s")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_stage2_flash_real():
    """Stage 2: Flash preprocess — classify signals with real LLM."""
    from marketmind.config.settings import MarketMindConfig
    from marketmind.pipeline.scout import fetch_all_sources
    from marketmind.pipeline.flash_preprocessor import preprocess_batch

    config = MarketMindConfig.from_env()
    items = await fetch_all_sources(config, use_cross_run_cache=False)
    assert len(items) > 0, "Need articles for preprocessing"

    t0 = time.time()
    signals = await preprocess_batch(items[:10])
    elapsed = time.time() - t0

    assert isinstance(signals, list), "preprocess_batch must return list"
    print(f"PASS: {len(signals)} signals from 10 articles in {elapsed:.1f}s")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_stage3_l1_real():
    """Stage 3: L1 narrative — deep analysis with real LLM."""
    from marketmind.config.settings import MarketMindConfig
    from marketmind.pipeline.scout import fetch_all_sources
    from marketmind.pipeline.flash_preprocessor import preprocess_batch
    from marketmind.pipeline.layer1_narrative import analyze_layer1

    config = MarketMindConfig.from_env()
    items = await fetch_all_sources(config, use_cross_run_cache=False)
    signals = await preprocess_batch(items[:10])

    t0 = time.time()
    result = await analyze_layer1(signals[:5], items[:10])
    elapsed = time.time() - t0

    assert result.event_grade, "L1 result must have event_grade"
    assert result.raw_analysis, "L1 result must have raw_analysis"
    print(f"PASS: grade={result.event_grade}, quadrant={result.matrix_quadrant} in {elapsed:.1f}s")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_stage4_l2_l3_real():
    """Stage 4: L2+L3 — fundamental + technical analysis with real LLM."""
    from marketmind.config.settings import MarketMindConfig
    from marketmind.pipeline.scout import fetch_all_sources
    from marketmind.pipeline.flash_preprocessor import preprocess_batch
    from marketmind.pipeline.layer1_narrative import analyze_layer1
    from marketmind.pipeline.layer2_fundamental import analyze_layer2
    from marketmind.pipeline.layer3_technical import analyze_layer3
    from marketmind.config.asset_universe import ASSET_UNIVERSE

    config = MarketMindConfig.from_env()
    items = await fetch_all_sources(config, use_cross_run_cache=False)
    signals = await preprocess_batch(items[:10])
    l1 = await analyze_layer1(signals[:5], items[:10])

    t0 = time.time()
    tickers = [a.ticker for a in list(ASSET_UNIVERSE.values())[:5]]
    l2, l3 = await asyncio.gather(analyze_layer2(l1), analyze_layer3(tickers, {}))
    elapsed = time.time() - t0

    assert l2.macro_quadrant, "L2 must have macro_quadrant"
    assert l3.results is not None, "L3 must have results"
    print(f"PASS: L2 quadrant={l2.macro_quadrant}, L3 tickers={len(l3.results)} in {elapsed:.1f}s")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_stage5_shadows_real():
    """Stage 5: Shadows — shadow ecosystem with real LLM votes."""
    from marketmind.config.settings import MarketMindConfig, ShadowSettings
    from marketmind.pipeline.scout import fetch_all_sources
    from marketmind.shadows.shadow_mother import ShadowMother
    from marketmind.shadows.shadow_state import ShadowStateDB
    from marketmind.shadows.expert_shadows import create_expert_shadows
    import tempfile

    config = MarketMindConfig.from_env()
    items = (await fetch_all_sources(config, use_cross_run_cache=False))[:20]
    news_dicts = [{"headline": item.title, "source": item.source_name} for item in items]

    fd, tmp = tempfile.mkstemp(suffix=".db")
    import os as _os; _os.close(fd)
    shadow_cfg = ShadowSettings(shadows_db_path=tmp)
    db = ShadowStateDB(tmp)
    db.init_schema()
    try:
        create_expert_shadows(db, shadow_cfg)
        mother = ShadowMother(shadow_cfg, db)
        t0 = time.time()
        result = await mother.orchestrate_daily_cycle(news_dicts, {})
        elapsed = time.time() - t0
        assert result.active_shadows > 0, "Must have active shadows"
        assert result.decisions_collected > 0, "Must have votes collected"
        print(f"PASS: {result.active_shadows} shadows, {result.decisions_collected} votes in {elapsed:.1f}s")
    finally:
        db.close()
        _os.unlink(tmp)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_stage6_red_team_real():
    """Stage 6: Red Team — adversarial challenge with real LLM."""
    from marketmind.config.settings import MarketMindConfig
    from marketmind.pipeline.scout import fetch_all_sources
    from marketmind.pipeline.flash_preprocessor import preprocess_batch
    from marketmind.pipeline.layer1_narrative import analyze_layer1
    from marketmind.pipeline.layer2_fundamental import analyze_layer2
    from marketmind.pipeline.red_team import run_red_team

    config = MarketMindConfig.from_env()
    items = await fetch_all_sources(config, use_cross_run_cache=False)
    signals = await preprocess_batch(items[:10])
    l1 = await analyze_layer1(signals[:5], items[:10])
    l2 = await analyze_layer2(l1)
    tickers = l2.ticker_candidates[:5] if l2.ticker_candidates else ["SPY", "QQQ"]

    t0 = time.time()
    report = await run_red_team(
        l1_raw=l1.raw_analysis,
        l2_raw=l2.raw_analysis,
        tickers=tickers,
    )
    elapsed = time.time() - t0

    assert isinstance(report.challenges, list), "Red Team report must have challenges list"
    assert report.a_grade_count >= 0, "a_grade_count must be >= 0"
    print(f"PASS: {len(report.challenges)} challenges, {report.a_grade_count} A-grade in {elapsed:.1f}s")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_stage7_resonance_real():
    """Stage 7: Resonance — statistical validation with DSR/CSCV framework."""
    from marketmind.pipeline.resonance import evaluate_resonance
    import random, math

    random.seed(42)
    signal_returns = {
        "momentum": [random.gauss(0.001, 0.015) for _ in range(100)],
        "value": [random.gauss(0.0005, 0.01) for _ in range(100)],
        "sentiment": [random.gauss(0.0008, 0.012) for _ in range(100)],
    }
    dimensions = ["momentum", "value", "sentiment"]
    all_rets = [r for rets in signal_returns.values() for r in rets]
    mean_ret = sum(all_rets) / len(all_rets)
    variance = sum((r - mean_ret) ** 2 for r in all_rets) / (len(all_rets) - 1)
    observed_sharpe = (mean_ret / math.sqrt(variance)) * math.sqrt(252)

    t0 = time.time()
    result = evaluate_resonance(signal_returns, dimensions, observed_sharpe)
    elapsed = time.time() - t0

    assert result.verdict, "Resonance verdict must be non-empty string"
    assert result.verdict in ("STRONG_SIGNAL", "WEAK_SIGNAL", "NO_SIGNAL"), \
        f"Unexpected verdict: {result.verdict}"
    print(f"PASS: verdict={result.verdict}, DSR={result.dsr}, PBO={result.pbo} in {elapsed:.3f}s")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_stage8_decision_real():
    """Stage 8: Decision — synthesis with real LLM."""
    from marketmind.config.settings import MarketMindConfig
    from marketmind.pipeline.scout import fetch_all_sources
    from marketmind.pipeline.flash_preprocessor import preprocess_batch
    from marketmind.pipeline.layer1_narrative import analyze_layer1
    from marketmind.pipeline.layer2_fundamental import analyze_layer2
    from marketmind.pipeline.layer3_technical import analyze_layer3
    from marketmind.pipeline.red_team import run_red_team
    from marketmind.pipeline.resonance import evaluate_resonance
    from marketmind.pipeline.decision import generate_decision
    import random, math

    config = MarketMindConfig.from_env()
    items = await fetch_all_sources(config, use_cross_run_cache=False)
    signals = await preprocess_batch(items[:10])
    l1 = await analyze_layer1(signals[:5], items[:10])
    l2 = await analyze_layer2(l1)
    tickers = l2.ticker_candidates[:5] if l2.ticker_candidates else ["SPY", "QQQ"]
    l3 = await analyze_layer3(tickers, {})

    red_team = await run_red_team(
        l1_raw=l1.raw_analysis,
        l2_raw=l2.raw_analysis,
        tickers=tickers,
    )

    random.seed(42)
    signal_returns = {
        "momentum": [random.gauss(0.001, 0.015) for _ in range(100)],
        "value": [random.gauss(0.0005, 0.01) for _ in range(100)],
    }
    dimensions = ["momentum", "value"]
    all_rets = [r for rets in signal_returns.values() for r in rets]
    mean_ret = sum(all_rets) / len(all_rets)
    variance = sum((r - mean_ret) ** 2 for r in all_rets) / (len(all_rets) - 1)
    observed_sharpe = (mean_ret / math.sqrt(variance)) * math.sqrt(252)
    resonance = evaluate_resonance(signal_returns, dimensions, observed_sharpe)

    t0 = time.time()
    decision = await generate_decision(l1, l2, l3, red_team, resonance)
    elapsed = time.time() - t0

    assert decision.decision_cards or decision.no_trade_card, \
        "Decision must have either decision_cards or no_trade_card"
    print(f"PASS: {len(decision.decision_cards)} cards, "
          f"no_trade={'yes' if decision.no_trade_card else 'no'} in {elapsed:.1f}s")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_stage9_archive_real():
    """Stage 9: Archive — save session using MarketMindArchive."""
    from marketmind.storage.archivist import get_archivist
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.time()
        archivist = get_archivist(tmp)
        try:
            archivist.ensure_dirs()
            filepath = archivist.save_json("analysis", "test_session", {
                "event_grade": "B",
                "matrix_quadrant": "core_opportunity",
                "timestamp": time.time(),
            })
            elapsed = time.time() - t0

            assert filepath.exists(), f"Archive file not created: {filepath}"
            print(f"PASS: archived to {filepath} in {elapsed:.1f}s")
        finally:
            archivist.close()
