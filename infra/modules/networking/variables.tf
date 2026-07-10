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
  description = "CIDR blocks for the public subnets, one per AZ. Two AZs is about placement resilience for a single task (ECS can start its replacement in the other AZ if one has a capacity issue), not real HA -- environments/dev's desired_count defaults to 1, so there is only ever one task running regardless of how many subnets it could land in."
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "tags" {
  description = "Common tags applied to all resources in this module."
  type        = map(string)
  default     = {}
}
