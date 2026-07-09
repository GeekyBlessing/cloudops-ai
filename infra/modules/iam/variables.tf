variable "name_prefix" {
  description = "Prefix applied to all IAM role/policy names created by this module, e.g. 'cloudops-ai-dev'."
  type        = string
}

variable "dynamodb_table_arn" {
  description = "ARN of the Incidents DynamoDB table -- every role needs read/write access to it, scoped exactly to this table (plus its GSIs)."
  type        = string
}

variable "sqs_queue_arn" {
  description = "ARN of the incident-triggers SQS queue (modules/eventbridge's queue_arn output) -- MonitoringReadOnlyRole needs consume permissions on it since the backend's SQS poller runs under that role, same as every other read-only investigative call it makes."
  type        = string
}

variable "tags" {
  description = "Common tags applied to all resources in this module."
  type        = map(string)
  default     = {}
}
