data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  artifact_bucket_name = "rise-artifacts-dev-${data.aws_caller_identity.current.account_id}"
}

# Module: VPC
module "vpc" {
  source = "../../modules/vpc"

  environment  = var.environment
  cluster_name = var.cluster_name
  vpc_cidr     = var.vpc_cidr
}

# Module: EKS Cluster
module "eks" {
  source = "../../modules/eks"

  environment        = var.environment
  cluster_name       = var.cluster_name
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids

  # Pinned EKS Node Group configuration
  instance_types = ["t3.medium"]
  desired_size   = 2
  min_size       = 1
  max_size       = 3
}

# S3 Bucket for Incident Artifacts
resource "aws_s3_bucket" "artifacts" {
  bucket        = local.artifact_bucket_name
  force_destroy = false

  tags = {
    Environment = var.environment
    Name        = local.artifact_bucket_name
  }
}

# Enable S3 Bucket Versioning
resource "aws_s3_bucket_versioning" "artifacts_versioning" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Enable Server-Side Encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts_encryption" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Block Public Access
resource "aws_s3_bucket_public_access_block" "artifacts_public_block" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Module: Least-Privilege IAM Roles
module "iam_roles" {
  source = "../../modules/iam_roles"

  environment             = var.environment
  cluster_name            = var.cluster_name
  vpc_id                  = module.vpc.vpc_id
  private_subnet_ids      = module.vpc.private_subnet_ids
  oidc_provider_arn       = module.eks.oidc_provider_arn
  oidc_provider_url       = module.eks.oidc_provider_url
  artifact_bucket_name    = aws_s3_bucket.artifacts.id
  log_group_prefix        = var.log_group_prefix
  alarm_prefix            = var.alarm_prefix
  remediation_lambda_name = var.remediation_lambda_name
  ssm_document_name       = var.ssm_document_name
  secret_name_prefix      = var.secret_name_prefix
}
