terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Environment = var.environment
      Project     = "RISE"
      ManagedBy   = "Terraform"
    }
  }
}

# Production EKS Module
module "eks" {
  source          = "../../modules/eks"
  cluster_name    = "rise-prod-cluster"
  cluster_version = var.cluster_version
  environment     = var.environment
  min_size        = var.node_group_min_size
  max_size        = var.node_group_max_size
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
            "${module.eks.oidc_provider}:sub" = "system:serviceaccount:rise-production:rise-agent-sa"
          }
        }
      }
    ]
  })
}

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
            "${module.eks.oidc_provider}:sub" = "system:serviceaccount:rise-production:external-secrets-sa"
          }
        }
      }
    ]
  })
}

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
