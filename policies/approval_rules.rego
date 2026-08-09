# OPA Policy - Approval Rules
package rise.policies.approval_rules

# Default-deny posture: require approval unless explicitly auto-approved
default requires_approval = true

# Explicit auto-approval criteria for non-production environments (staging/dev)
requires_approval = false {
    input.environment != "production"
    input.risk_tier == "low"
    input.confidence >= input.min_confidence
    input.blast_radius_count <= input.max_blast_radius
}

requires_approval = false {
    input.environment != "production"
    input.risk_tier == "medium"
    input.confidence >= input.min_confidence
    input.blast_radius_count <= input.max_blast_radius
}

# Production auto-approval criteria: ONLY allowed when an explicit matching policy permits it
requires_approval = false {
    input.environment == "production"
    some i
    policy := input.policies[i]
    policy.action_pattern == input.action_type
    policy.environment == "production"
    policy.requires_approval == false
    input.confidence >= input.min_confidence
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
    policy.action_pattern == input.action_type
    policy.environment == "production"
    policy.requires_approval == false
}

reasons[reason] {
    input.risk_tier == "critical"
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
    input.risk_tier == "high"
    reason := "High-risk action in production requires human approval"
}

reasons[reason] {
    input.action_type == "code_fix_pr"
    reason := "Code fix PR requires mandatory human merge review"
}

