variable "name_prefix" {
  description = "Prefix applied to all resources created by this module, e.g. 'cloudops-ai-dev'."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for the public subnets (one per AZ) -- now used by modules/alb's load balancer, not the backend task itself. Two AZs is about the ALB's own resilience, not the task's -- environments/dev's desired_count defaults to 1, so there is only ever one task running regardless of how many private subnets it could land in."
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for the private subnets (one per AZ) -- where the backend Fargate task actually runs now. Outbound internet access goes through the single NAT gateway this module creates; there is no inbound route at all except via modules/alb's load balancer, which lives in the public subnets and reaches into these over the security group modules/ecs configures."
  type        = list(string)
  default     = ["10.0.11.0/24", "10.0.12.0/24"]
}

variable "tags" {
  description = "Common tags applied to all resources in this module."
  type        = map(string)
  default     = {}
}
