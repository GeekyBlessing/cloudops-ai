variable "table_name" {
  description = "Name of the DynamoDB table for incident records. Matches CLOUDOPS_DYNAMODB_TABLE_INCIDENTS on the backend."
  type        = string
  default     = "cloudops-ai-incidents"
}

variable "billing_mode" {
  description = "PAY_PER_REQUEST is the default -- incident volume for an on-call system is spiky and low relative to typical DynamoDB workloads, so on-demand billing avoids provisioning (and paying for) capacity that sits idle most of the time. Switch to PROVISIONED with autoscaling only if cost modeling shows on-demand is actually more expensive at your real traffic."
  type        = string
  default     = "PAY_PER_REQUEST"
}

variable "tags" {
  description = "Common tags applied to all resources in this module."
  type        = map(string)
  default     = {}
}
