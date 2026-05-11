"""Tests for EmergencyQuotaAuditor -- confidence-based extra LLM calls with reward/penalty state machine."""
import pytest
from datetime import datetime, timezone

from projects.marketmind.shadows.shadow_state import (
    ShadowStateDB, ShadowConfig, EmergencyQuotaRequest
)
from projects.marketmind.config.settings import ShadowSettings
# Module under test (will be created)
from projects.marketmind.shadows.emergency_quota import (
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


def test_emergency_quota_approved_when_confidence_8_plus(auditor):
    """Emergency quota request should be approved when confidence >= 8."""
    result = auditor.request_quota(
        "expert:gold:test_auditor",
        "Gold breakout on COMEX above $2500 resistance",
        confidence=9,
    )
    assert result is True


def test_emergency_quota_denied_below_confidence_8(auditor):
    """Emergency quota request should be denied when confidence < 8."""
    result = auditor.request_quota(
        "expert:gold:test_auditor",
        "Mild gold uptick",
        confidence=5,
    )
    assert result is False


def test_emergency_quota_denied_when_penalized(auditor):
    """Emergency quota should be denied while shadow is in penalized state."""
    # First, trigger a penalty by requesting and then failing an audit
    auditor.request_quota(
        "expert:gold:test_auditor",
        "Gold breakout",
        confidence=9,
    )
    # Simulate auditing the pending request
    pending = auditor.state_db.get_pending_emergency_audits()
    assert len(pending) == 1
    quota_id = pending[0].id if hasattr(pending[0], 'id') else 1
    # We need to get the actual ID from DB
    # Record the result as a loss (not followed)
    auditor.audit_result(quota_id, was_profitable=False, was_followed=False)
    # Now try to request again while penalized
    result = auditor.request_quota(
        "expert:gold:test_auditor",
        "Another gold breakout",
        confidence=9,
    )
    assert result is False


def test_profitable_emergency_gains_permanent_quota(auditor):
    """A profitable emergency quota should result in permanent +1 bonus."""
    auditor.request_quota(
        "expert:gold:test_auditor",
        "Gold breakout opportunity",
        confidence=9,
    )
    pending = auditor.state_db.get_pending_emergency_audits()
    quota_id = pending[0].id if hasattr(pending[0], 'id') else 1

    state = auditor.audit_result(quota_id, was_profitable=True, was_followed=True)
    assert state.permanent_bonus == 1
    assert state.consecutive_failures == 0
    assert state.state == "rewarded"


def test_loss_not_followed_penalty_3_days(auditor):
    """A loss that was not followed should result in 3-day observation penalty."""
    auditor.request_quota(
        "expert:gold:test_auditor",
        "Gold breakout opportunity",
        confidence=9,
    )
    pending = auditor.state_db.get_pending_emergency_audits()
    quota_id = pending[0].id if hasattr(pending[0], 'id') else 1

    state = auditor.audit_result(quota_id, was_profitable=False, was_followed=False)
    assert state.state == "penalized"
    assert state.observation_days_remaining == 3
    assert state.consecutive_failures == 1


def test_loss_followed_penalty_7_days(auditor):
    """A loss that was followed should result in 7-day observation penalty."""
    auditor.request_quota(
        "expert:gold:test_auditor",
        "Gold breakout opportunity",
        confidence=9,
    )
    pending = auditor.state_db.get_pending_emergency_audits()
    quota_id = pending[0].id if hasattr(pending[0], 'id') else 1

    state = auditor.audit_result(quota_id, was_profitable=False, was_followed=True)
    assert state.state == "penalized"
    assert state.observation_days_remaining == 7
    assert state.consecutive_failures == 1


def test_three_consecutive_failures_permanent_minus_one(auditor):
    """Three consecutive failures should trigger permanent -1 quota penalty.

    Simulates the real lifecycle: request -> audit -> reset to normal
    (penalty expires) -> repeat. On the 3rd failure, permanent -1 triggers.
    """
    state = None
    for i in range(3):
        result = auditor.request_quota(
            "expert:gold:test_auditor",
            f"Gold breakout attempt {i+1}",
            confidence=9,
        )
        assert result is True, f"Request {i+1} should be approved"

        pending = auditor.state_db.get_pending_emergency_audits()
        quota_id = pending[-1].id
        state = auditor.audit_result(quota_id, was_profitable=False, was_followed=False)

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


def test_confidence_calibration_tracked(temp_shadow_db, settings):
    """Confidence reports should be tracked for calibration analysis.

    Uses separate shadows for each confidence level since only one pending
    emergency quota per shadow is allowed at a time.
    """
    auditor = EmergencyQuotaAuditor(temp_shadow_db, settings)

    for conf, idx in [(8, 0), (9, 1), (10, 2)]:
        shadow_id = f"expert:test:calib_{idx}"
        config = ShadowConfig(
            shadow_id=shadow_id,
            shadow_type="expert",
            display_name=f"Calibration Shadow {idx}",
            methodology_prompt="Test",
            virtual_capital=10000.0,
        )
        temp_shadow_db.create_shadow(config)
        auditor.request_quota(
            shadow_id,
            f"Gold opportunity at confidence {conf}",
            confidence=conf,
        )

    # Verify all requests are recorded
    pending = auditor.state_db.get_pending_emergency_audits()
    confidences = [p.confidence_self_report for p in pending]
    assert 8 in confidences
    assert 9 in confidences
    assert 10 in confidences


def test_get_shadow_state_returns_defaults_for_new_shadow(auditor):
    """get_shadow_state should return default EmergencyQuotaState for a new shadow."""
    state = auditor.get_shadow_state("expert:gold:test_auditor")
    assert state.shadow_id == "expert:gold:test_auditor"
    assert state.state == "normal"
    assert state.consecutive_failures == 0
    assert state.permanent_bonus == 0
    assert state.permanent_penalty == 0
    assert state.observation_days_remaining == 0
