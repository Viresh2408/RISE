# OPA Policy - Approval Rules
package rise.policies.approval_rules

# Default-deny posture: require approval unless explicitly auto-approved
default requires_approval = true

# Explicit auto-approval criteria
requires_approval = false {
    input.risk_tier == "low"
    input.confidence >= input.min_confidence
    input.blast_radius_count <= input.max_blast_radius
}

requires_approval = false {
    input.risk_tier == "medium"
    input.environment != "production"
    input.confidence >= input.min_confidence
    input.blast_radius_count <= input.max_blast_radius
}

# Collect reasons for human approval requirements
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
