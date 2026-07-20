variable "domain_name" {
  description = "The apex domain this hosted zone is authoritative for, e.g. cloudops-ai.dev."
  type        = string
}

variable "tags" {
  description = "Tags applied to the hosted zone."
  type        = map(string)
  default     = {}
}
