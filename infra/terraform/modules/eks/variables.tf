variable "environment" {
  description = "Deployment environment name"
  type        = string
}

variable "cluster_name" {
  description = "Name of the EKS cluster"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where EKS nodes will be deployed"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for EKS node groups"
  type        = list(string)
}

variable "instance_types" {
  description = "Pinned EC2 instance types for EKS node group"
  type        = list(string)
  default     = ["t3.medium"]
}

variable "desired_size" {
  description = "Explicit desired capacity for node group"
  type        = number
  default     = 2
}

variable "min_size" {
  description = "Explicit minimum node count for node group"
  type        = number
  default     = 1
}

variable "max_size" {
  description = "Explicit maximum node count for node group"
  type        = number
  default     = 3
}
