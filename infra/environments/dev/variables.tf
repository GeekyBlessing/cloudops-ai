variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "image_tag" {
  description = "Docker image tag to deploy -- deploy.yml always passes this explicitly as the triggering commit's git SHA (e.g. -var=\"image_tag=abc123f\"), never a mutable tag like 'latest'. No default: a `terraform plan`/`apply` run without it fails fast and asks for one interactively, rather than silently deploying whatever 'latest' happens to point at. For a plan-only run (CI's terraform-plan.yml) any placeholder string works, since the image doesn't need to actually exist for `plan` to compute a diff -- see ecs module's container_image usage."
  type        = string
}

variable "desired_count" {
  type    = number
  default = 1
}
