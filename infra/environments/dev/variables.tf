variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "container_image" {
  description = "Backend container image URI. No default -- must be set explicitly (via terraform.tfvars or -var) once an image has actually been built and pushed. See infra/README.md; the build/push pipeline itself is a separate, not-yet-built piece of this project."
  type        = string
}

variable "desired_count" {
  type    = number
  default = 1
}
