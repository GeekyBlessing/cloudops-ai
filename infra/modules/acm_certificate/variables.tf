variable "domain_name" {
  description = "Primary domain name the certificate covers, e.g. cloudops-ai.dev."
  type        = string
}

variable "subject_alternative_names" {
  description = "Additional names the certificate should cover, e.g. [\"www.cloudops-ai.dev\"]."
  type        = list(string)
  default     = []
}

variable "zone_id" {
  description = "Route53 hosted zone ID (from the route53 module) to create DNS validation records in."
  type        = string
}

variable "tags" {
  description = "Tags applied to the certificate."
  type        = map(string)
  default     = {}
}
