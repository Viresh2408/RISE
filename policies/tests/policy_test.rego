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
		"policies": [],
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
