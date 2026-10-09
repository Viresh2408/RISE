# OPA Policy - Approval Rules
package rise.policies.approval_rules

# Default-deny posture: require approval unless explicitly auto-approved
default requires_approval = true

# Every environment requires an explicit administrator-created policy. Derive
# risk from the authoritative risk package, not a caller's claimed risk tier.
requires_approval = false {
    risk := data.rise.policies.risk_tiers.risk_level
    {"low", "medium"}[risk]
    some i
    policy := input.policies[i]
    object.get(policy, "active", true) == true
    policy.action_pattern == input.action_type
    policy.environment == input.environment
    policy.risk_tier == risk
    policy.requires_approval == false
    input.confidence >= input.min_confidence
    input.confidence >= policy.min_confidence
    input.blast_radius_count <= input.max_blast_radius
    input.blast_radius_count <= policy.max_blast_radius
}

# Collect reasons for human approval requirements
reasons[reason] {
    input.environment == "production"
    not has_prod_auto_approval_policy
    reason := "Production auto-remediation locked in shadow mode — no active policy permits auto-approval for this action type"
}

has_prod_auto_approval_policy {
    some i
    policy := input.policies[i]
    object.get(policy, "active", true) == true
    policy.action_pattern == input.action_type
    policy.environment == "production"
    policy.requires_approval == false
}

reasons[reason] {
    data.rise.policies.risk_tiers.risk_level == "critical"
    reason := "Risk tier is critical - mandatory human approval required"
}

reasons[reason] {
    input.confidence < input.min_confidence
    reason := sprintf("Root cause confidence (%v) below required threshold (%v)", [input.confidence, input.min_confidence])
}

reasons[reason] {
    input.blast_radius_count > input.max_blast_radius
    reason := sprintf("Blast radius services count (%v) exceeds maximum allowed (%v)", [input.blast_radius_count, input.max_blast_radius])
}

reasons[reason] {
    input.environment == "production"
    data.rise.policies.risk_tiers.risk_level == "high"
    reason := "High-risk action in production requires human approval"
}

reasons[reason] {
    input.action_type == "code_fix_pr"
    reason := "Code fix PR requires mandatory human merge review"
}
