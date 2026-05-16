"""Tests for EmergencyQuotaAuditor -- confidence-based extra LLM calls with reward/penalty state machine."""
import json
import pytest
from datetime import datetime, timezone

from marketmind.shadows.shadow_state import (
    ShadowStateDB, ShadowConfig, EmergencyQuotaRequest
)
from marketmind.config.settings import ShadowSettings
# Module under test (will be created)
from marketmind.shadows.emergency_quota import (
    EmergencyQuotaState, EmergencyQuotaAuditor
)


@pytest.fixture
def settings():
    return ShadowSettings(
        emergency_confidence_threshold=8,
        emergency_extra_calls=3,
        emergency_profit_reward_perm=True,
        emergency_loss_penalty_days=3,
        emergency_loss_followed_penalty_days=7,
        emergency_consecutive_fail_limit=3,
    )


@pytest.fixture
def auditor(temp_shadow_db, settings):
    """Create an auditor with a registered shadow in the DB."""
    config = ShadowConfig(
        shadow_id="expert:gold:test_auditor",
        shadow_type="expert",
        display_name="Test Gold Bug",
        methodology_prompt="You are a gold expert.",
        virtual_capital=50000.0,
        domain="gold",
    )
    temp_shadow_db.create_shadow(config)
    return EmergencyQuotaAuditor(temp_shadow_db, settings)


@pytest.mark.asyncio
async def test_emergency_quota_approved_when_confidence_8_plus(auditor):
    """Emergency quota request should be approved when confidence >= 8."""
    result = await auditor.request_quota(
        "expert:gold:test_auditor",
        "Gold breakout on COMEX above $2500 resistance",
        base_quota_used=5, base_quota_total=5,
    )
    assert result is True


@pytest.mark.asyncio
async def test_emergency_quota_denied_quota_not_exhausted(auditor):
    """Emergency quota request should be denied when base quota not exhausted."""
    result = await auditor.request_quota(
        "expert:gold:test_auditor",
        "Mild gold uptick",
        base_quota_used=2, base_quota_total=5,
    )
    assert result is False


@pytest.mark.asyncio
async def test_emergency_quota_denied_when_penalized(auditor):
    """Emergency quota should be denied while shadow is in penalized state."""
    # First, trigger a penalty by requesting and then failing an audit
    await auditor.request_quota(
        "expert:gold:test_auditor",
        "Gold breakout",
        base_quota_used=5, base_quota_total=5,
    )
    # Simulate auditing the pending request
    pending = auditor.state_db.get_pending_emergency_audits()
    assert len(pending) == 1
    quota_id = pending[0].id if hasattr(pending[0], 'id') else 1
    # We need to get the actual ID from DB
    # Record the result as a loss (not followed)
    await auditor.audit_result(quota_id, was_profitable=False, was_followed=False)
    # Now try to request again while penalized
    result = await auditor.request_quota(
        "expert:gold:test_auditor",
        "Another gold breakout",
        base_quota_used=5, base_quota_total=5,
    )
    assert result is False


@pytest.mark.asyncio
async def test_profitable_emergency_gains_permanent_quota(auditor):
    """A profitable emergency quota should result in permanent +1 bonus."""
    await auditor.request_quota(
        "expert:gold:test_auditor",
        "Gold breakout opportunity",
        base_quota_used=5, base_quota_total=5,
    )
    pending = auditor.state_db.get_pending_emergency_audits()
    quota_id = pending[0].id if hasattr(pending[0], 'id') else 1

    state = await auditor.audit_result(quota_id, was_profitable=True, was_followed=True)
    assert state.permanent_bonus == 1
    assert state.consecutive_failures == 0
    assert state.state == "rewarded"


@pytest.mark.asyncio
async def test_loss_not_followed_penalty_3_days(auditor):
    """A loss that was not followed should result in 3-day observation penalty."""
    await auditor.request_quota(
        "expert:gold:test_auditor",
        "Gold breakout opportunity",
        base_quota_used=5, base_quota_total=5,
    )
    pending = auditor.state_db.get_pending_emergency_audits()
    quota_id = pending[0].id if hasattr(pending[0], 'id') else 1

    state = await auditor.audit_result(quota_id, was_profitable=False, was_followed=False)
    assert state.state == "penalized"
    assert state.observation_days_remaining == 3
    assert state.consecutive_failures == 1


@pytest.mark.asyncio
async def test_loss_followed_penalty_7_days(auditor):
    """A loss that was followed should result in 7-day observation penalty."""
    await auditor.request_quota(
        "expert:gold:test_auditor",
        "Gold breakout opportunity",
        base_quota_used=5, base_quota_total=5,
    )
    pending = auditor.state_db.get_pending_emergency_audits()
    quota_id = pending[0].id if hasattr(pending[0], 'id') else 1

    state = await auditor.audit_result(quota_id, was_profitable=False, was_followed=True)
    assert state.state == "penalized"
    assert state.observation_days_remaining == 7
    assert state.consecutive_failures == 1


@pytest.mark.asyncio
async def test_three_consecutive_failures_permanent_minus_one(auditor):
    """Three consecutive failures should trigger permanent -1 quota penalty.

    Simulates the real lifecycle: request -> audit -> reset to normal
    (penalty expires) -> repeat. On the 3rd failure, permanent -1 triggers.
    """
    state = None
    for i in range(3):
        result = await auditor.request_quota(
            "expert:gold:test_auditor",
            f"Gold breakout attempt {i+1}",
            base_quota_used=5, base_quota_total=5,
        )
        assert result is True, f"Request {i+1} should be approved"

        pending = auditor.state_db.get_pending_emergency_audits()
        quota_id = pending[-1].id
        state = await auditor.audit_result(quota_id, was_profitable=False, was_followed=False)

        if i < 2:
            # Simulate penalty expiring (reset to normal for next iteration)
            assert state.state == "penalized"
            state.state = "normal"
            state.observation_days_remaining = 0
            auditor._shadow_states["expert:gold:test_auditor"] = state

    # On the 3rd consecutive failure, permanent penalty should trigger
    assert state.permanent_penalty == 1
    # consecutive_failures reset to 0 after penalty applied
    assert state.consecutive_failures == 0


@pytest.mark.asyncio
async def test_exhaustion_quota_requests_tracked(temp_shadow_db, settings):
    """Emergency quota requests should be tracked with exhaustion status.

    Uses separate shadows since only one pending emergency quota per shadow.
    """
    auditor = EmergencyQuotaAuditor(temp_shadow_db, settings)

    for idx in range(3):
        shadow_id = f"expert:test:calib_{idx}"
        config = ShadowConfig(
            shadow_id=shadow_id,
            shadow_type="expert",
            display_name=f"Calibration Shadow {idx}",
            methodology_prompt="Test",
            virtual_capital=10000.0,
        )
        temp_shadow_db.create_shadow(config)
        await auditor.request_quota(
            shadow_id,
            f"Gold opportunity at quota exhaustion #{idx}",
            base_quota_used=5, base_quota_total=5,
        )

    # Verify all requests are recorded
    pending = auditor.state_db.get_pending_emergency_audits()
    assert len(pending) == 3


def test_get_shadow_state_returns_defaults_for_new_shadow(auditor):
    """get_shadow_state should return default EmergencyQuotaState for a new shadow."""
    state = auditor.get_shadow_state("expert:gold:test_auditor")
    assert state.shadow_id == "expert:gold:test_auditor"
    assert state.state == "normal"
    assert state.consecutive_failures == 0
    assert state.permanent_bonus == 0
    assert state.permanent_penalty == 0
    assert state.observation_days_remaining == 0


@pytest.mark.asyncio
async def test_state_survives_recreation(temp_shadow_db, sample_expert_config):
    """Recreating Auditor restores state from DB."""
    from marketmind.shadows.emergency_quota import EmergencyQuotaAuditor
    settings = ShadowSettings()
    temp_shadow_db.create_shadow(sample_expert_config)

    auditor1 = EmergencyQuotaAuditor(temp_shadow_db, settings)
    await auditor1.request_quota(sample_expert_config.shadow_id, "test opportunity", 9)
    state1 = auditor1.get_shadow_state(sample_expert_config.shadow_id)
    assert state1.state == "pending"

    # Create new instance — should restore from DB
    auditor2 = EmergencyQuotaAuditor(temp_shadow_db, settings)
    state2 = auditor2.get_shadow_state(sample_expert_config.shadow_id)
    assert state2.state == "pending"


@pytest.mark.asyncio
async def test_state_persisted_after_audit_result(temp_shadow_db, sample_expert_config):
    """audit_result() persists state to DB."""
    from marketmind.shadows.emergency_quota import EmergencyQuotaAuditor
    from marketmind.shadows.shadow_state import EmergencyQuotaRequest
    from datetime import datetime, timezone

    settings = ShadowSettings()
    temp_shadow_db.create_shadow(sample_expert_config)

    auditor = EmergencyQuotaAuditor(temp_shadow_db, settings)
    await auditor.request_quota(sample_expert_config.shadow_id, "test", 9)

    # Find pending quota via DB
    pending = temp_shadow_db.get_pending_emergency_audits()
    assert len(pending) > 0
    quota_id = pending[0].id

    state = await auditor.audit_result(quota_id, was_profitable=True, was_followed=True)
    assert state.state == "rewarded"

    # Verify from DB
    raw = temp_shadow_db.load_emergency_quota_state(sample_expert_config.shadow_id)
    assert raw is not None
    data = json.loads(raw)
    assert data["state"] == "rewarded"


def test_corrupted_runtime_state_graceful(temp_shadow_db, sample_expert_config):
    """Corrupted DB state falls back to defaults gracefully."""
    from marketmind.shadows.emergency_quota import EmergencyQuotaAuditor

    settings = ShadowSettings()
    temp_shadow_db.create_shadow(sample_expert_config)
    # Write corrupted JSON
    temp_shadow_db.save_emergency_quota_state(sample_expert_config.shadow_id, "not valid json{{{")

    auditor = EmergencyQuotaAuditor(temp_shadow_db, settings)
    state = auditor.get_shadow_state(sample_expert_config.shadow_id)
    # Should fall back to defaults
    assert state.state == "normal"
    assert state.consecutive_failures == 0
