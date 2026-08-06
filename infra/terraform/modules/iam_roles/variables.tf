variable "environment" {
  description = "Deployment environment name"
  type        = string
}

variable "oidc_provider_arn" {
  description = "ARN of the EKS OIDC identity provider"
  type        = string
}

variable "oidc_provider_url" {
  description = "URL of the EKS OIDC identity provider"
  type        = string
}

variable "cluster_name" {
  description = "Name of the EKS cluster for resource ARN scoping"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID for network resource scoping"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for network resource scoping"
  type        = list(string)
}

variable "artifact_bucket_name" {
  description = "S3 bucket name for incident artifact storage"
  type        = string
}

# Forward-referenced infrastructure variables (NO default values set, required explicit inputs)
variable "log_group_prefix" {
  description = "Prefix for forward-referenced CloudWatch log groups created by application/observability pipelines"
  type        = string
}

variable "alarm_prefix" {
  description = "Prefix for forward-referenced CloudWatch alarms created by observability pipelines"
  type        = string
}

variable "remediation_lambda_name" {
  description = "Name of forward-referenced Lambda function for automated remediation"
  type        = string
}

variable "ssm_document_name" {
  description = "Name of forward-referenced SSM document for automated remediation commands"
  type        = string
}

variable "secret_name_prefix" {
  description = "Secret name prefix in Secrets Manager for integration credentials"
  type        = string
}
