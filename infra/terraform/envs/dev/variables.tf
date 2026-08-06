variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment identifier"
  type        = string
  default     = "dev"
}

variable "cluster_name" {
  description = "EKS Cluster Name"
  type        = string
  default     = "rise-dev-eks"
}

variable "vpc_cidr" {
  description = "CIDR block for the dev VPC"
  type        = string
  default     = "10.0.0.0/16"
}

# Forward-referenced infrastructure variables (NO default values set, required explicit inputs)
variable "log_group_prefix" {
  description = "Prefix for forward-referenced CloudWatch log groups"
  type        = string
}

variable "alarm_prefix" {
  description = "Prefix for forward-referenced CloudWatch alarms"
  type        = string
}

variable "remediation_lambda_name" {
  description = "Name of forward-referenced Lambda remediation function"
  type        = string
}

variable "ssm_document_name" {
  description = "Name of forward-referenced SSM document"
  type        = string
}

variable "secret_name_prefix" {
  description = "Prefix for secrets stored in Secrets Manager"
  type        = string
}
