output "eks_cluster_endpoint" {
  description = "EKS production cluster endpoint"
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_name" {
  description = "EKS production cluster name"
  value       = module.eks.cluster_name
}

output "eks_cluster_arn" {
  description = "EKS production cluster ARN"
  value       = module.eks.cluster_arn
}

output "vpc_id" {
  description = "The ID of the production VPC"
  value       = module.vpc.vpc_id
}

output "k8s_remediation_role_arn" {
  description = "ARN of the scoped k8s remediation IRSA role"
  value       = aws_iam_role.rise_k8s_remediation_role.arn
}

output "external_secrets_role_arn" {
  description = "ARN of the External Secrets Operator IRSA role"
  value       = aws_iam_role.external_secrets_role.arn
}
