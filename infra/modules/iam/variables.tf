variable "name_prefix" {
  description = "Prefix applied to all IAM role/policy names created by this module, e.g. 'cloudops-ai-dev'."
  type        = string
}

variable "dynamodb_table_arn" {
  description = "ARN of the Incidents DynamoDB table -- every role needs read/write access to it, scoped exactly to this table (plus its GSIs)."
  type        = string
}

variable "tags" {
  description = "Common tags applied to all resources in this module."
  type        = map(string)
  default     = {}
}
