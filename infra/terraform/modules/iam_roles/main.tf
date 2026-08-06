data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  oidc_url_stripped = replace(var.oidc_provider_url, "https://", "")
}

# ==============================================================================
# 1. Ingestion & Observability Role
# Service Account: system:serviceaccount:rise-observability:observability-sa
# Rationale: Enables ingestion and monitoring services to pull CloudWatch logs
# and metric data for anomaly detection and incident correlation.
# ==============================================================================
resource "aws_iam_role" "ingestion_observability" {
  name = "rise-${var.environment}-ingestion-observability-role"

  assume_role_policy = jsonencode({
    "Version" = "2012-10-17"
    "Statement" = [
      {
        "Effect" = "Allow"
        "Principal" = {
          "Federated" = var.oidc_provider_arn
        }
        "Action" = "sts:AssumeRoleWithWebIdentity"
        "Condition" = {
          "StringEquals" = {
            "${local.oidc_url_stripped}:sub" = "system:serviceaccount:rise-observability:observability-sa"
          }
        }
      }
    ]
  })

  tags = {
    Environment = var.environment
    Category    = "ingestion-observability"
  }
}

# Policy for CloudWatch logs and metrics read-only access
# Scoped strictly to specific CloudWatch log group prefix and CloudWatch alarm prefix
# Note: Log groups and alarms are forward-references to resources created by observability pipelines.
resource "aws_iam_policy" "ingestion_observability" {
  name        = "rise-${var.environment}-ingestion-observability-policy"
  description = "Scoped read access for CloudWatch logs and metric alarms"

  policy = jsonencode({
    "Version" = "2012-10-17"
    "Statement" = [
      {
        # Scope: Reading CloudWatch log streams within the specific application log group prefix.
        # Action: Explicit read-only log retrieval actions (no log modification or deletion).
        # Resource: Prefix-scoped log group path under /aws/rise/<env>/*. Never bare '*'.
        "Sid"    = "CloudWatchLogsReadAccess"
        "Effect" = "Allow"
        "Action" = [
          "logs:FilterLogEvents",
          "logs:GetLogEvents",
          "logs:DescribeLogStreams"
        ]
        "Resource" = [
          "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:${var.log_group_prefix}/*",
          "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:${var.log_group_prefix}"
        ]
      },
      {
        # Scope: Retrieving CloudWatch metric statistics and alarm states.
        # Action: Explicit metric reading actions.
        # Resource: Prefix-scoped alarm ARNs for RISE monitoring. Never bare '*'.
        "Sid"    = "CloudWatchMetricsReadAccess"
        "Effect" = "Allow"
        "Action" = [
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics"
        ]
        "Resource" = [
          "arn:aws:cloudwatch:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:alarm:${var.alarm_prefix}-*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ingestion_observability" {
  role       = aws_iam_role.ingestion_observability.name
  policy_arn = aws_iam_policy.ingestion_observability.arn
}

# ==============================================================================
# 2. Context & Investigation Service Role
# Service Account: system:serviceaccount:rise-agents:context-investigation-sa
# Rationale: Enables context builder agents to inspect AWS infrastructure, VPC
# topology, and EKS cluster configuration during incident investigation.
# ==============================================================================
resource "aws_iam_role" "context_investigation" {
  name = "rise-${var.environment}-context-investigation-role"

  assume_role_policy = jsonencode({
    "Version" = "2012-10-17"
    "Statement" = [
      {
        "Effect" = "Allow"
        "Principal" = {
          "Federated" = var.oidc_provider_arn
        }
        "Action" = "sts:AssumeRoleWithWebIdentity"
        "Condition" = {
          "StringEquals" = {
            "${local.oidc_url_stripped}:sub" = "system:serviceaccount:rise-agents:context-investigation-sa"
          }
        }
      }
    ]
  })

  tags = {
    Environment = var.environment
    Category    = "context-investigation"
  }
}

# Policy for EC2, VPC, and EKS cluster metadata read-only inspection
resource "aws_iam_policy" "context_investigation" {
  name        = "rise-${var.environment}-context-investigation-policy"
  description = "Scoped read-only inspection of VPC network resources and EKS cluster"

  policy = jsonencode({
    "Version" = "2012-10-17"
    "Statement" = [
      {
        # Scope: Reading VPC, subnet, and security group metadata for incident context graph.
        # Action: Explicit Describe operations only (no mutation).
        # Resource: Fully-qualified VPC and Subnet ARNs. Never bare '*'.
        "Sid"    = "VpcNetworkInspection"
        "Effect" = "Allow"
        "Action" = [
          "ec2:DescribeInstances",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSubnets",
          "ec2:DescribeVpcs"
        ]
        "Resource" = concat(
          [
            "arn:aws:ec2:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:vpc/${var.vpc_id}"
          ],
          [for subnet_id in var.private_subnet_ids : "arn:aws:ec2:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:subnet/${subnet_id}"]
        )
      },
      {
        # Scope: Describing the RISE EKS cluster and node group metadata during investigation.
        # Action: Explicit EKS Describe and List operations.
        # Resource: Exact EKS Cluster ARN. Never bare '*'.
        "Sid"    = "EksClusterInspection"
        "Effect" = "Allow"
        "Action" = [
          "eks:DescribeCluster",
          "eks:ListNodegroups"
        ]
        "Resource" = [
          "arn:aws:eks:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:cluster/${var.cluster_name}"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "context_investigation" {
  role       = aws_iam_role.context_investigation.name
  policy_arn = aws_iam_policy.context_investigation.arn
}

# ==============================================================================
# 3. Artifact Storage Role
# Service Account: system:serviceaccount:rise-api:api-artifacts-sa
# Rationale: Allows the API gateway service to read, write, and delete incident logs
# and artifacts in the S3 bucket using pre-signed URLs or direct S3 SDK calls.
# ==============================================================================
resource "aws_iam_role" "s3_artifact" {
  name = "rise-${var.environment}-s3-artifact-role"

  assume_role_policy = jsonencode({
    "Version" = "2012-10-17"
    "Statement" = [
      {
        "Effect" = "Allow"
        "Principal" = {
          "Federated" = var.oidc_provider_arn
        }
        "Action" = "sts:AssumeRoleWithWebIdentity"
        "Condition" = {
          "StringEquals" = {
            "${local.oidc_url_stripped}:sub" = "system:serviceaccount:rise-api:api-artifacts-sa"
          }
        }
      }
    ]
  })

  tags = {
    Environment = var.environment
    Category    = "artifact-storage"
  }
}

# Policy for S3 Artifact Storage bucket access
resource "aws_iam_policy" "s3_artifact" {
  name        = "rise-${var.environment}-s3-artifact-policy"
  description = "Scoped bucket list and object CRUD permissions for incident artifact bucket"

  policy = jsonencode({
    "Version" = "2012-10-17"
    "Statement" = [
      {
        # Scope: Bucket-level listing and location check.
        # Action: Explicit list and location actions.
        # Resource: Exact S3 Bucket ARN. Never bare '*'.
        "Sid"    = "S3BucketLevelAccess"
        "Effect" = "Allow"
        "Action" = [
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        "Resource" = [
          "arn:aws:s3:::${var.artifact_bucket_name}"
        ]
      },
      {
        # Scope: Reading, uploading, and removing incident artifacts (tenant_id/incident_id/artifact_id path).
        # Action: Explicit Object-level CRUD actions.
        # Resource: Prefix-scoped object key path matching rise artifact hierarchy (bucket/*). Never bare '*'.
        "Sid"    = "S3ObjectLevelAccess"
        "Effect" = "Allow"
        "Action" = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        "Resource" = [
          "arn:aws:s3:::${var.artifact_bucket_name}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "s3_artifact" {
  role       = aws_iam_role.s3_artifact.name
  policy_arn = aws_iam_policy.s3_artifact.arn
}

# ==============================================================================
# 4. Bedrock AI Inference Role
# Service Account: system:serviceaccount:rise-agents:agent-worker-sa
# Rationale: Enables multi-agent reasoning workers (LangGraph runtime) to call AWS Bedrock
# LLMs (Claude 3.5 Sonnet, Titan Embeddings) for reasoning and summarization.
# ==============================================================================
resource "aws_iam_role" "bedrock_ai" {
  name = "rise-${var.environment}-bedrock-ai-role"

  assume_role_policy = jsonencode({
    "Version" = "2012-10-17"
    "Statement" = [
      {
        "Effect" = "Allow"
        "Principal" = {
          "Federated" = var.oidc_provider_arn
        }
        "Action" = "sts:AssumeRoleWithWebIdentity"
        "Condition" = {
          "StringEquals" = {
            "${local.oidc_url_stripped}:sub" = "system:serviceaccount:rise-agents:agent-worker-sa"
          }
        }
      }
    ]
  })

  tags = {
    Environment = var.environment
    Category    = "ai-inference"
  }
}

# Policy for AWS Bedrock model invocation scoped strictly to designated foundation models
resource "aws_iam_policy" "bedrock_ai" {
  name        = "rise-${var.environment}-bedrock-ai-policy"
  description = "Scoped model invocation permissions for specific AWS Bedrock models"

  policy = jsonencode({
    "Version" = "2012-10-17"
    "Statement" = [
      {
        # Scope: Invoking specific approved LLMs and embedding models on AWS Bedrock.
        # Action: Explicit InvokeModel actions.
        # Resource: Fully-qualified Bedrock foundation model ARNs. Never bare '*'.
        "Sid"    = "BedrockModelInvocation"
        "Effect" = "Allow"
        "Action" = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:GetFoundationModel"
        ]
        "Resource" = [
          "arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/anthropic.claude-3-5-sonnet-20240620-v1:0",
          "arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/amazon.titan-embed-text-v1"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "bedrock_ai" {
  role       = aws_iam_role.bedrock_ai.name
  policy_arn = aws_iam_policy.bedrock_ai.arn
}

# ==============================================================================
# 5. Remediation Cloud Actions Role
# Service Account: system:serviceaccount:rise-agents:execution-agent-sa
# Rationale: Allows execution agents to perform approved automated remediation via
# AWS SSM run command documents and designated Lambda remediation functions.
# ==============================================================================
resource "aws_iam_role" "execution_cloud_actions" {
  name = "rise-${var.environment}-execution-cloud-actions-role"

  assume_role_policy = jsonencode({
    "Version" = "2012-10-17"
    "Statement" = [
      {
        "Effect" = "Allow"
        "Principal" = {
          "Federated" = var.oidc_provider_arn
        }
        "Action" = "sts:AssumeRoleWithWebIdentity"
        "Condition" = {
          "StringEquals" = {
            "${local.oidc_url_stripped}:sub" = "system:serviceaccount:rise-agents:execution-agent-sa"
          }
        }
      }
    ]
  })

  tags = {
    Environment = var.environment
    Category    = "remediation-execution"
  }
}

# Policy for SSM document execution and Lambda invocation
# Note: SSM document and Lambda function are forward-references to remediation tools deployed elsewhere.
resource "aws_iam_policy" "execution_cloud_actions" {
  name        = "rise-${var.environment}-execution-cloud-actions-policy"
  description = "Scoped permissions for SSM command execution and Lambda remediation calls"

  policy = jsonencode({
    "Version" = "2012-10-17"
    "Statement" = [
      {
        # Scope: Executing pre-approved SSM run command document.
        # Action: Explicit SSM command execution actions.
        # Resource: Parameterized SSM document ARN and command prefix ARNs. Never bare '*'.
        "Sid"    = "SsmRunCommandExecution"
        "Effect" = "Allow"
        "Action" = [
          "ssm:SendCommand",
          "ssm:GetCommandInvocation"
        ]
        "Resource" = [
          "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:document/${var.ssm_document_name}",
          "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:ssm-command/rise-${var.environment}-*"
        ]
      },
      {
        # Scope: Triggering designated Lambda remediation handler function.
        # Action: Explicit Lambda invocation actions.
        # Resource: Parameterized Lambda function ARN. Never bare '*'.
        "Sid"    = "LambdaRemediationInvocation"
        "Effect" = "Allow"
        "Action" = [
          "lambda:InvokeFunction",
          "lambda:GetFunction"
        ]
        "Resource" = [
          "arn:aws:lambda:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:function:${var.remediation_lambda_name}"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "execution_cloud_actions" {
  role       = aws_iam_role.execution_cloud_actions.name
  policy_arn = aws_iam_policy.execution_cloud_actions.arn
}

# ==============================================================================
# 6. Integration Secrets Role
# Service Account: system:serviceaccount:rise-api:api-secrets-sa
# Rationale: Enables API services to retrieve encrypted external integration credentials
# (GitHub, Slack, PagerDuty keys) stored in AWS Secrets Manager under rise/<env>/*.
# ==============================================================================
resource "aws_iam_role" "secrets_manager" {
  name = "rise-${var.environment}-secrets-manager-role"

  assume_role_policy = jsonencode({
    "Version" = "2012-10-17"
    "Statement" = [
      {
        "Effect" = "Allow"
        "Principal" = {
          "Federated" = var.oidc_provider_arn
        }
        "Action" = "sts:AssumeRoleWithWebIdentity"
        "Condition" = {
          "StringEquals" = {
            "${local.oidc_url_stripped}:sub" = "system:serviceaccount:rise-api:api-secrets-sa"
          }
        }
      }
    ]
  })

  tags = {
    Environment = var.environment
    Category    = "secrets-management"
  }
}

# Policy for Secrets Manager read-only secret retrieval
resource "aws_iam_policy" "secrets_manager" {
  name        = "rise-${var.environment}-secrets-manager-policy"
  description = "Scoped read access for integration credentials in Secrets Manager"

  policy = jsonencode({
    "Version" = "2012-10-17"
    "Statement" = [
      {
        # Scope: Reading secret value and metadata for secrets under rise/<env>/ prefix.
        # Action: Explicit secret get/describe actions.
        # Resource: Prefix-scoped secret ARN pattern. Never bare '*'.
        "Sid"    = "SecretsManagerReadAccess"
        "Effect" = "Allow"
        "Action" = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        "Resource" = [
          "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:${var.secret_name_prefix}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "secrets_manager" {
  role       = aws_iam_role.secrets_manager.name
  policy_arn = aws_iam_policy.secrets_manager.arn
}
