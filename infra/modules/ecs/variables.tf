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
  description = "Subnets the Fargate task's ENI is placed in -- from modules/networking's private_subnet_ids output (not public anymore). The task has no public IP; modules/alb's load balancer, in the public subnets, is the only inbound path."
  type        = list(string)
}

variable "alb_security_group_id" {
  description = "From modules/alb's alb_security_group_id output. The task's security group only accepts inbound traffic sourced from this security group -- see this module's main.tf docstring for why that replaced the old CIDR-block-based ingress."
  type        = string
}

variable "target_group_arn" {
  description = "From modules/alb's target_group_arn output. Wired into the aws_ecs_service's load_balancer block so ECS registers/deregisters running tasks against it automatically as the service scales or replaces tasks."
  type        = string
}

variable "health_check_grace_period_seconds" {
  description = "How long a newly-started task gets before the ALB's health check failures start counting against it. Needs to comfortably exceed image pull + application startup time -- too short and a slow-starting task gets cycled before it ever passes a check; too long just delays noticing a task that's genuinely stuck."
  type        = number
  default     = 60
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
