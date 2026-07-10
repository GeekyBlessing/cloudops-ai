variable "name_prefix" {
  description = "Prefix applied to all resources created by this module, e.g. 'cloudops-ai-dev'."
  type        = string
}

variable "container_image" {
  description = "Full image URI for the backend container, e.g. '<account>.dkr.ecr.<region>.amazonaws.com/cloudops-ai-backend:latest'. No default -- there is no sensible generic image to fall back to; a real image must be built and pushed first (not yet part of this repo -- see infra/README.md)."
  type        = string
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "vpc_id" {
  description = "VPC the task's security group lives in -- from modules/networking's vpc_id output."
  type        = string
}

variable "subnet_ids" {
  description = "Subnets the Fargate task's ENI is placed in -- from modules/networking's public_subnet_ids output. Public, not private: the task still needs assign_public_ip=true to be directly reachable since there's no ALB yet (see infra/README.md)."
  type        = list(string)
}

variable "allowed_ingress_cidr_blocks" {
  description = "CIDR blocks allowed to reach the API port directly. Defaults to 0.0.0.0/0 (open to the internet) for portfolio-demo simplicity -- the same trade-off this module always had, just now a named, overridable variable instead of a literal buried in the security group resource. A real deployment could narrow this to a specific office/VPN CIDR, or (better) drop direct exposure entirely once an ALB module exists to front the task instead."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "task_role_arn" {
  description = "IAM role the running container assumes at the application level -- from modules/iam's ecs_task_role_arn output."
  type        = string
}

variable "execution_role_arn" {
  description = "IAM role ECS itself uses to pull the image and write logs -- distinct from task_role_arn, which is what the application code assumes. From modules/iam's ecs_task_execution_role_arn output."
  type        = string
}

variable "cpu" {
  description = "Fargate task CPU units (256 = 0.25 vCPU) -- the smallest Fargate size, sized for a low-traffic portfolio deployment, not production load."
  type        = number
  default     = 256
}

variable "memory" {
  description = "Fargate task memory in MiB."
  type        = number
  default     = 512
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "environment" {
  description = "Environment variables passed into the container, as a list of {name, value} objects (the exact shape ECS's container_definitions JSON expects)."
  type = list(object({
    name  = string
    value = string
  }))
  default = []
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "tags" {
  description = "Common tags applied to all resources in this module."
  type        = map(string)
  default     = {}
}
