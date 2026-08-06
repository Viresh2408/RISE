# OPA Policy - Tool Allow-list Policy
package rise.policies.tool_allowlist

# Default to deny (default-deny posture)
default allow = false

# Allowed execution-agent write/execute tools
write_tools := {
    "restart_pod",
    "rollback_deployment",
    "scale_deployment",
    "restart_ec2_instance",
    "invoke_lambda",
    "update_ssm_parameter",
    "create_branch",
    "create_pr",
    "run_workflow"
}

# Allowed read-only tools for Context Builder / Investigation Agents
read_tools := {
    "get_pod_status",
    "get_pod_logs",
    "get_events",
    "get_cloudwatch_alarms",
    "get_cloudwatch_logs",
    "get_iam_context",
    "get_recent_commits",
    "get_pr_diff",
    "get_workflow_status",
    "query_prometheus",
    "query_loki",
    "query_alertmanager",
    "search_similar_incidents",
    "search_runbooks"
}

# 1. Execution agent allowed write/execute tools in authorized environments
allow {
    input.agent_identity == "execution-agent"
    write_tools[input.tool_name]
    input.environment != "unauthorized"
}

# 2. Execution agent allowed read tools
allow {
    input.agent_identity == "execution-agent"
    read_tools[input.tool_name]
}

# 3. Read-only agents allowed read tools
allow {
    input.agent_identity == "context-builder-agent"
    read_tools[input.tool_name]
}

allow {
    input.agent_identity == "investigation-agent"
    read_tools[input.tool_name]
}

# Allow evaluation reasons
reasons[reason] {
    not allow
    reason := sprintf("Tool '%v' is not permitted for agent '%v' in environment '%v'", [input.tool_name, input.agent_identity, input.environment])
}
