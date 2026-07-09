variable "name_prefix" {
  description = "Prefix applied to the repository name, e.g. 'cloudops-ai-dev' -> repository 'cloudops-ai-dev-backend'."
  type        = string
}

variable "untagged_image_expiry_days" {
  description = "Untagged images (superseded layers from old builds, failed pushes) are deleted after this many days via a lifecycle policy. Tagged images (anything actually deployed, referenced by git SHA) are never auto-deleted -- only untagged cruft."
  type        = number
  default     = 7
}

variable "tags" {
  type    = map(string)
  default = {}
}
