output "vpc_id" {
  description = "The ID of the VPC"
  value       = module.vpc.vpc_id
}

output "eks_cluster_endpoint" {
  description = "Endpoint for EKS control plane"
  value       = module.eks.cluster_endpoint
}

output "artifact_bucket_name" {
  description = "Name of the incident artifact S3 bucket"
  value       = aws_s3_bucket.artifacts.id
}

output "iam_role_arns" {
  description = "ARNs of the provisioned IRSA least-privilege IAM roles"
  value = {
    ingestion_observability   = module.iam_roles.ingestion_observability_role_arn
    context_investigation     = module.iam_roles.context_investigation_role_arn
    s3_artifact               = module.iam_roles.s3_artifact_role_arn
    bedrock_ai                = module.iam_roles.bedrock_ai_role_arn
    execution_cloud_actions   = module.iam_roles.execution_cloud_actions_role_arn
    secrets_manager           = module.iam_roles.secrets_manager_role_arn
  }
}
