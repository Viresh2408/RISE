output "ingestion_observability_role_arn" {
  description = "ARN of the Ingestion & Observability IRSA role"
  value       = aws_iam_role.ingestion_observability.arn
}

output "context_investigation_role_arn" {
  description = "ARN of the Context & Investigation IRSA role"
  value       = aws_iam_role.context_investigation.arn
}

output "s3_artifact_role_arn" {
  description = "ARN of the S3 Artifact Storage IRSA role"
  value       = aws_iam_role.s3_artifact.arn
}

output "bedrock_ai_role_arn" {
  description = "ARN of the Bedrock AI Inference IRSA role"
  value       = aws_iam_role.bedrock_ai.arn
}

output "execution_cloud_actions_role_arn" {
  description = "ARN of the Remediation Cloud Actions IRSA role"
  value       = aws_iam_role.execution_cloud_actions.arn
}

output "secrets_manager_role_arn" {
  description = "ARN of the Secrets Manager IRSA role"
  value       = aws_iam_role.secrets_manager.arn
}
