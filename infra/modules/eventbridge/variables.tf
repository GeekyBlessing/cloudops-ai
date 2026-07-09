variable "name_prefix" {
  description = "Prefix applied to all resources created by this module, e.g. 'cloudops-ai-dev'."
  type        = string
}

variable "guardduty_severity_threshold" {
  description = "Minimum GuardDuty finding severity (0.0-10.0 scale) that triggers an incident. Matches GUARDDUTY_SEVERITY_THRESHOLD in backend/src/cloudops_ai/agents/security_agent.py -- kept in sync by convention (Terraform can't import a Python constant), not by any automated check. If you change one, change the other."
  type        = number
  default     = 4.0
}

variable "message_retention_seconds" {
  description = "How long an unconsumed message survives in the queue before SQS drops it. Default 4 days -- generous enough that a backend outage over a weekend doesn't silently lose incident triggers."
  type        = number
  default     = 345600 # 4 days
}

variable "visibility_timeout_seconds" {
  description = "How long a message is hidden from other receivers after the poller picks it up, before becoming visible again if not deleted. Needs to comfortably exceed the time a full graph.invoke() run can take (LLM calls included) -- set generously since a too-short timeout causes the same event to be processed twice, and a too-long one only delays retry of a genuinely failed message."
  type        = number
  default     = 120
}

variable "max_receive_count" {
  description = "How many times a message can be received before SQS moves it to the dead-letter queue instead of redelivering it -- protects against a single malformed event looping forever."
  type        = number
  default     = 3
}

variable "tags" {
  type    = map(string)
  default = {}
}
