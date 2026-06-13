variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-2"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "lab"
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "otel-lab"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
}

variable "node_instance_type" {
  description = "EC2 instance type for EKS nodes — t3.xlarge minimum for Cilium + Beyla + OTel Collector"
  type        = string
  default     = "t3.xlarge"
}

variable "node_count" {
  description = "Number of EKS worker nodes"
  type        = number
  default     = 3
}
