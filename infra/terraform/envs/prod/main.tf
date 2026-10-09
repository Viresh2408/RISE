data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  # EKS OIDC provider host (issuer URL without the https:// scheme), used to
  # scope IRSA trust conditions to specific Kubernetes service accounts.
  oidc_provider_host = replace(module.eks.oidc_provider_url, "https://", "")
}

# Module: VPC (prod has its own isolated network; AZs must match aws_region)
module "vpc" {
  source = "../../modules/vpc"

  environment          = var.environment
  cluster_name         = var.cluster_name
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
}

# Module: Production EKS Cluster
module "eks" {
  source = "../../modules/eks"

  environment        = var.environment
  cluster_name       = var.cluster_name
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids

  instance_types = var.node_instance_types
  desired_size   = var.node_group_desired_size
  min_size       = var.node_group_min_size
  max_size       = var.node_group_max_size
}

# Scoped Least-Privilege IAM Roles per Action Category (No wildcard * actions)
resource "aws_iam_role" "rise_k8s_remediation_role" {
  name = "rise-prod-k8s-remediation-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRoleWithWebIdentity"
        Effect = "Allow"
        Principal = {
          Federated = module.eks.oidc_provider_arn
        }
        Condition = {
          StringEquals = {
            "${local.oidc_provider_host}:sub" = "system:serviceaccount:rise-production:rise-agent-sa"
          }
        }
      }
    ]
  })
}
# <<APPEND_MARKER>>

# Scoped Policy for Pod Restart & Deployment Scaling (Explicit actions, no wildcard *)
resource "aws_iam_policy" "rise_k8s_remediation_policy" {
  name        = "rise-prod-k8s-remediation-policy"
  description = "Least-privilege policy for k8s pod restart and deployment scaling"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "eks:DescribeCluster",
          "eks:DescribeNodegroup"
        ]
        Resource = module.eks.cluster_arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "rise_k8s_remediation_attach" {
  role       = aws_iam_role.rise_k8s_remediation_role.name
  policy_arn = aws_iam_policy.rise_k8s_remediation_policy.arn
}

# External Secrets Operator Integration Role
resource "aws_iam_role" "external_secrets_role" {
  name = "rise-prod-external-secrets-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRoleWithWebIdentity"
        Effect = "Allow"
        Principal = {
          Federated = module.eks.oidc_provider_arn
        }
        Condition = {
          StringEquals = {
            "${local.oidc_provider_host}:sub" = "system:serviceaccount:rise-production:external-secrets-sa"
          }
        }
      }
    ]
  })
}
# <<APPEND_MARKER2>>

resource "aws_iam_policy" "external_secrets_policy" {
  name        = "rise-prod-external-secrets-policy"
  description = "Allows External Secrets Operator to read scoped SSM secrets"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:*:secret:rise/production/*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "external_secrets_attach" {
  role       = aws_iam_role.external_secrets_role.name
  policy_arn = aws_iam_policy.external_secrets_policy.arn
}
