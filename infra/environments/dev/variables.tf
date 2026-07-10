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

variable "alert_email" {
  description = "Email address subscribed to modules/monitoring's SNS alerts topic. No default and left null unless set -- see modules/monitoring's alert_email variable description for what happens if you don't set it (the topic and every alarm still get created, just nothing is notified until a subscription exists)."
  type        = string
  default     = null
}
