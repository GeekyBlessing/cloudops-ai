variable "name_prefix" {
  description = "Prefix applied to all resources created by this module, e.g. 'cloudops-ai-dev'."
  type        = string
}

variable "vpc_id" {
  description = "From modules/networking's vpc_id output."
  type        = string
}

variable "public_subnet_ids" {
  description = "From modules/networking's public_subnet_ids output -- the ALB lives here even though the backend task itself has moved to the private subnets."
  type        = list(string)
}

variable "target_port" {
  description = "Port the backend container listens on -- must match modules/ecs's container_port (both default to 8000)."
  type        = number
  default     = 8000
}

variable "health_check_path" {
  description = "Path the target group polls to decide whether a task is healthy. Defaults to the backend's unauthenticated /health endpoint (backend/src/cloudops_ai/main.py) -- the ALB has no way to attach an X-API-Key header to a health check, so this has to be a route require_api_key never touches, same reasoning as the ECS task health check documented in api/dependencies.py."
  type        = string
  default     = "/health"
}

variable "ingress_cidr_blocks" {
  description = "CIDR blocks allowed to reach the ALB on port 80. Defaults to 0.0.0.0/0 (open to the internet) for portfolio-demo simplicity -- this is now the *only* place in the stack with direct internet exposure; modules/ecs's security group only accepts traffic from this module's security group, not from the internet directly."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "tags" {
  description = "Common tags applied to all resources in this module."
  type        = map(string)
  default     = {}
}
