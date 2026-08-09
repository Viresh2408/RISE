output "eks_cluster_endpoint" {
  description = "EKS production cluster endpoint"
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_name" {
  description = "EKS production cluster name"
  value       = module.eks.cluster_name
}
