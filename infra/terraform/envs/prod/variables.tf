variable "aws_region" {
  description = "AWS region for production deployment"
  type        = string
  default     = "us-west-2"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "production"
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "rise-prod-cluster"
}

variable "vpc_cidr" {
  description = "CIDR block for the production VPC"
  type        = string
  default     = "10.1.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones for subnet distribution (must belong to aws_region)"
  type        = list(string)
  default     = ["us-west-2a", "us-west-2b"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets"
  type        = list(string)
  default     = ["10.1.1.0/24", "10.1.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets"
  type        = list(string)
  default     = ["10.1.10.0/24", "10.1.11.0/24"]
}

variable "node_group_desired_size" {
  description = "Desired EKS node count"
  type        = number
  default     = 3
}

variable "node_group_min_size" {
  description = "Minimum EKS node count"
  type        = number
  default     = 3
}

variable "node_group_max_size" {
  description = "Maximum EKS node count"
  type        = number
  default     = 10
}

variable "node_instance_types" {
  description = "EC2 instance types for the production node group"
  type        = list(string)
  default     = ["t3.large"]
}
