"""Phase 8 Production Shadow Mode & Launch Checklist Integration Tests.

Tests:
1. Structural Shadow Mode default posture (zero active auto-approve policies -> requires_approval=True).
2. Section 6.5 Granular Policy Unlock (restart_pod on OOMKill auto-approves, BUT EVERY OTHER action type still requires approval).
3. Tested Emergency-Disable Path (deactivating/deleting unlocked policy immediately restores 100% human-approval posture).
4. Explicit checkable human sign-off verification in `docs/shadow-mode-burnin-report.md`.
5. Launch Checklist DoD criteria from `implementation-guide.md §8`.
"""

import os
import pytest
from apps.agents.src.engines.risk_engine import RiskEngine


def test_structural_shadow_mode_default():
    """Verify that with zero active auto-approve policies, production defaults to shadow mode (requires_approval=True)."""
    engine = RiskEngine()

    # 1. Derived indicator check
    assert engine.is_shadow_mode_active(active_policies=[]) is True

    # 2. Evaluate low-risk action in production with no active policies
    eval_result = engine.evaluate_risk_local_fallback(
        action_type="restart_pod",
        environment="production",
        blast_radius_count=1,
        confidence=0.95,
        min_confidence=0.70,
        active_policies=[],
    )

    # Must require approval
    assert eval_result.requires_approval is True
    assert any("shadow mode" in r for r in eval_result.reasons)


def test_section_6_5_granular_unlock_isolation():
    """Verify that unlocking restart_pod on OOMKill ONLY auto-approves restart_pod, while ALL OTHER action types still require approval."""
    engine = RiskEngine()

    # Active policy row created via POST /policies for restart_pod on OOMKill
    restart_pod_policy = [
        {
            "id": "pol-001",
            "action_pattern": "restart_pod",
            "environment": "production",
            "risk_tier": "low",
            "requires_approval": False,
            "max_blast_radius": 1,
            "condition": "OOMKill",
        }
    ]

    # Derived indicator shows shadow mode is no longer 100% active globally
    assert engine.is_shadow_mode_active(active_policies=restart_pod_policy) is False

    # 1. restart_pod matching policy -> Auto-approved!
    restart_eval = engine.evaluate_risk_local_fallback(
        action_type="restart_pod",
        environment="production",
        blast_radius_count=1,
        confidence=0.95,
        min_confidence=0.70,
        active_policies=restart_pod_policy,
    )
    assert restart_eval.requires_approval is False, "restart_pod matching unlock policy should auto-approve"

    # 2. GRANULAR ISOLATION CHECK: Test ALL OTHER action types -> MUST ALL STILL REQUIRE APPROVAL!
    other_action_types = [
        "clear_cache",
        "flush_redis",
        "scale_deployment",
        "rollback_deployment",
        "failover_database",
        "modify_traffic",
        "delete_database",
        "drop_table",
        "code_fix_pr",
        "restart_service",
    ]

    for action_type in other_action_types:
        other_eval = engine.evaluate_risk_local_fallback(
            action_type=action_type,
            environment="production",
            blast_radius_count=1,
            confidence=0.95,
            min_confidence=0.70,
            active_policies=restart_pod_policy,
        )
        assert other_eval.requires_approval is True, f"Action type '{action_type}' must STILL require approval after restart_pod unlock"


def test_emergency_disable_path():
    """Verify that deactivating/deleting the unlock policy immediately forces restart_pod back to requiring human approval."""
    engine = RiskEngine()

    active_policy = [
        {
            "id": "pol-001",
            "action_pattern": "restart_pod",
            "environment": "production",
            "requires_approval": False,
            "max_blast_radius": 1,
        }
    ]

    # Confirm active policy auto-approves
    res1 = engine.evaluate_risk_local_fallback(
        action_type="restart_pod",
        environment="production",
        blast_radius_count=1,
        confidence=0.95,
        active_policies=active_policy,
    )
    assert res1.requires_approval is False

    # TRIGGER EMERGENCY DISABLE PATH: Deactivate policy (set requires_approval=True or remove policy row)
    deactivated_policy = [
        {
            "id": "pol-001",
            "action_pattern": "restart_pod",
            "environment": "production",
            "requires_approval": True,  # Deactivated
            "max_blast_radius": 1,
        }
    ]

    res2 = engine.evaluate_risk_local_fallback(
        action_type="restart_pod",
        environment="production",
        blast_radius_count=1,
        confidence=0.95,
        active_policies=deactivated_policy,
    )
    assert res2.requires_approval is True, "Emergency deactivation MUST instantly revert restart_pod to requiring human approval"
    assert engine.is_shadow_mode_active(active_policies=deactivated_policy) is True


def test_explicit_human_signoff_in_burnin_report():
    """Explicitly verify that `docs/shadow-mode-burnin-report.md` contains human review sign-off block."""
    report_path = "docs/shadow-mode-burnin-report.md"
    assert os.path.exists(report_path), "shadow-mode-burnin-report.md must exist"

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "SIGNED_OFF" in content or "APPROVED" in content, "Burn-in report must contain status signed off"
    assert "Reviewed By" in content, "Burn-in report must contain 'Reviewed By' signature"
    assert "SHADOW_MODE_BURNIN_HUMAN_REVIEWED_AND_SIGNED_OFF" in content, "Burn-in report must contain explicit token"




def test_launch_checklist_items_verification():
    """Verify all 12 launch checklist items from implementation-guide.md §8."""
    checklist_path = "docs/launch-checklist-signoff.md"
    assert os.path.exists(checklist_path), "launch-checklist-signoff.md must exist"

    with open(checklist_path, "r", encoding="utf-8") as f:
        content = f.read()

    checked_count = content.count("- [x]")
    assert checked_count >= 12, f"Launch checklist must have at least 12 checked items, found {checked_count}"
