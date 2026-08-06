# OPA Policy - Risk Tiers Definition
package rise.policies.risk_tiers

# Default to critical risk tier for unmapped/unrecognized inputs (default-deny posture)
default risk_level = "critical"

# Defined action categories
critical_actions := {"delete_database", "drop_table", "force_destroy", "code_fix_pr", "destroy_cluster"}
high_actions := {"rollback_deployment", "failover_database", "modify_traffic", "scale_deployment"}
medium_actions := {"restart_service", "clear_cache", "flush_redis", "restart_pod"}
low_actions := {"restart_pod", "clear_cache", "flush_redis", "scale_deployment"}

# Helpers
is_critical {
    critical_actions[input.action_type]
}
is_critical {
    input.blast_radius_count > 3
}
is_critical {
    input.service_criticality == "tier0"
}
is_critical {
    input.service_criticality == "mission_critical"
}

is_high {
    not is_critical
    high_actions[input.action_type]
    input.environment == "production"
}
is_high {
    not is_critical
    input.blast_radius_count >= 2
    input.environment == "production"
}

is_medium {
    not is_critical
    not is_high
    medium_actions[input.action_type]
    input.environment == "production"
}
is_medium {
    not is_critical
    not is_high
    high_actions[input.action_type]
    input.environment == "staging"
}
is_medium {
    not is_critical
    not is_high
    high_actions[input.action_type]
    input.environment == "dev"
}

is_low {
    not is_critical
    not is_high
    not is_medium
    low_actions[input.action_type]
    input.environment == "staging"
    input.blast_radius_count <= 1
}
is_low {
    not is_critical
    not is_high
    not is_medium
    low_actions[input.action_type]
    input.environment == "dev"
    input.blast_radius_count <= 1
}

# Rule evaluation
risk_level = "critical" { is_critical }
risk_level = "high" { is_high }
risk_level = "medium" { is_medium }
risk_level = "low" { is_low }
