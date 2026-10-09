# OPA Policy Unit Tests
#
# Run with: opa test policies/ -v
#
# Covers the three real policies the Risk Engine evaluates upstream of the MCP gateway:
#   - rise.policies.tool_allowlist   (default-deny tool allow-list)
#   - rise.policies.risk_tiers       (action -> risk_level classification)
#   - rise.policies.approval_rules   (when human approval is required)
package rise.policies.tests

import data.rise.policies.approval_rules
import data.rise.policies.risk_tiers
import data.rise.policies.tool_allowlist

# --------------------------------------------------------------------------- #
# tool_allowlist
# --------------------------------------------------------------------------- #

test_execution_agent_write_tool_allowed {
	tool_allowlist.allow with input as {
		"agent_identity": "execution-agent",
		"tool_name": "restart_pod",
		"environment": "staging",
	}
}

test_readonly_agent_denied_write_tool {
	not tool_allowlist.allow with input as {
		"agent_identity": "context-builder-agent",
		"tool_name": "restart_pod",
		"environment": "staging",
	}
}

test_readonly_agent_allowed_read_tool {
	tool_allowlist.allow with input as {
		"agent_identity": "investigation-agent",
		"tool_name": "get_pod_logs",
		"environment": "staging",
	}
}

test_unknown_tool_denied {
	not tool_allowlist.allow with input as {
		"agent_identity": "execution-agent",
		"tool_name": "rm_minus_rf",
		"environment": "staging",
	}
}

test_unauthorized_environment_denied {
	not tool_allowlist.allow with input as {
		"agent_identity": "execution-agent",
		"tool_name": "restart_pod",
		"environment": "unauthorized",
	}
}

# --------------------------------------------------------------------------- #
# risk_tiers
# --------------------------------------------------------------------------- #

test_code_fix_pr_is_critical {
	risk_tiers.risk_level == "critical" with input as {
		"action_type": "code_fix_pr",
		"environment": "production",
		"blast_radius_count": 1,
		"service_criticality": "normal",
	}
}

test_large_blast_radius_is_critical {
	risk_tiers.risk_level == "critical" with input as {
		"action_type": "restart_pod",
		"environment": "production",
		"blast_radius_count": 5,
		"service_criticality": "normal",
	}
}

test_unmapped_action_defaults_critical {
	risk_tiers.risk_level == "critical" with input as {
		"action_type": "totally_unknown_action",
		"environment": "production",
		"blast_radius_count": 0,
		"service_criticality": "normal",
	}
}

test_low_risk_pod_restart_in_staging {
	risk_tiers.risk_level == "low" with input as {
		"action_type": "restart_pod",
		"environment": "staging",
		"blast_radius_count": 1,
		"service_criticality": "normal",
	}
}

# --------------------------------------------------------------------------- #
# approval_rules
# --------------------------------------------------------------------------- #

test_production_requires_approval_by_default {
	approval_rules.requires_approval with input as {
		"environment": "production",
		"risk_tier": "high",
		"confidence": 0.99,
		"min_confidence": 0.9,
		"blast_radius_count": 1,
		"max_blast_radius": 3,
		"action_type": "rollback_deployment",
		"policies": [],
	}
}

test_low_risk_staging_auto_approved {
	not approval_rules.requires_approval with input as {
		"environment": "staging",
		"risk_tier": "low",
		"confidence": 0.95,
		"min_confidence": 0.9,
		"blast_radius_count": 1,
		"max_blast_radius": 3,
		"action_type": "restart_pod",
        "policies": [{"action_pattern": "restart_pod", "environment": "staging", "risk_tier": "low", "requires_approval": false, "min_confidence": 0.9, "max_blast_radius": 1}],
	}
}

test_staging_without_explicit_policy_requires_approval {
    approval_rules.requires_approval with input as {
        "environment": "staging", "action_type": "restart_pod", "confidence": 0.99,
        "min_confidence": 0.9, "blast_radius_count": 1, "max_blast_radius": 1, "policies": [],
    }
}

test_low_confidence_requires_approval {
	approval_rules.requires_approval with input as {
		"environment": "staging",
		"risk_tier": "low",
		"confidence": 0.5,
		"min_confidence": 0.9,
		"blast_radius_count": 1,
		"max_blast_radius": 3,
		"action_type": "restart_pod",
		"policies": [],
	}
}

# A scoped policy may tighten the global limits but cannot relax them or
# authorize a different action, environment, or authoritative risk tier.
scoped_policy := {
    "action_pattern": "restart_pod", "environment": "staging", "risk_tier": "low",
    "active": true, "requires_approval": false, "min_confidence": 0.9, "max_blast_radius": 1,
}

scoped_input := {
    "environment": "staging", "action_type": "restart_pod", "confidence": 0.95,
    "min_confidence": 0.9, "blast_radius_count": 1, "max_blast_radius": 2,
    "policies": [scoped_policy],
}

test_inactive_policy_cannot_authorize {
    policy := object.union(scoped_policy, {"active": false})
    approval_rules.requires_approval with input as object.union(scoped_input, {"policies": [policy]})
}

test_foreign_environment_policy_cannot_authorize {
    policy := object.union(scoped_policy, {"environment": "production"})
    approval_rules.requires_approval with input as object.union(scoped_input, {"policies": [policy]})
}

test_wrong_risk_scope_cannot_authorize {
    policy := object.union(scoped_policy, {"risk_tier": "medium"})
    approval_rules.requires_approval with input as object.union(scoped_input, {"policies": [policy]})
}

test_policy_confidence_limit_cannot_be_relaxed {
    policy := object.union(scoped_policy, {"min_confidence": 0.99})
    approval_rules.requires_approval with input as object.union(scoped_input, {"policies": [policy]})
}

test_policy_blast_radius_limit_cannot_be_relaxed {
    policy := object.union(scoped_policy, {"max_blast_radius": 0})
    approval_rules.requires_approval with input as object.union(scoped_input, {"policies": [policy]})
}

test_claimed_low_risk_cannot_override_critical_action {
    policy := object.union(scoped_policy, {"action_pattern": "drop_table"})
    scenario := object.union(scoped_input, {"action_type": "drop_table", "risk_tier": "low", "policies": [policy]})
    approval_rules.requires_approval with input as scenario
}
