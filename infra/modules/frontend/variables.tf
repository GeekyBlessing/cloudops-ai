variable "name_prefix" {
  description = "Prefix applied to all resource names created by this module."
  type        = string
}

variable "alb_dns_name" {
  description = "DNS name of the ALB fronting the backend ECS service (infra/modules/alb's alb_dns_name output). Used as CloudFront's second origin so API requests never leave AWS's own network as plaintext across the public internet -- only ALB->CloudFront is HTTP, and that hop stays inside AWS."
  type        = string
}

variable "api_path_patterns" {
  description = <<-EOT
    CloudFront path patterns that should be routed to the ALB origin instead
    of the S3 origin. The backend has no unifying "/api" prefix (see
    infra/README.md), so this lists every real top-level route explicitly.
    If a new top-level router is added to backend/src/cloudops_ai/main.py,
    its path patterns need to be added here too, or CloudFront will try to
    serve it out of the S3 bucket and return a SPA-fallback 404 instead of
    hitting the backend.
  EOT
  type    = list(string)
  default = ["/health", "/incidents", "/incidents/*", "/remediation", "/remediation/*"]
}

variable "price_class" {
  description = "CloudFront price class. PriceClass_100 (US/Canada/Europe edge locations only) is the cheapest tier -- a deliberate cost trade-off for a portfolio project, documented in infra/README.md."
  type        = string
  default     = "PriceClass_100"
}

variable "default_root_object" {
  description = "Object CloudFront serves for requests to the distribution root ('/')."
  type        = string
  default     = "index.html"
}

variable "tags" {
  description = "Tags applied to all resources created by this module."
  type        = map(string)
  default     = {}
}
