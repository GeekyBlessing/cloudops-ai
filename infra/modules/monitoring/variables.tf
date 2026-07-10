variable "name_prefix" {
  description = "Prefix applied to all resources created by this module, e.g. 'cloudops-ai-dev'."
  type        = string
}

variable "ecs_cluster_name" {
  description = "From modules/ecs's cluster_name output -- dimension for the ECS CPU/memory alarms."
  type        = string
}

variable "ecs_service_name" {
  description = "From modules/ecs's service_name output -- dimension for the ECS CPU/memory alarms."
  type        = string
}

variable "sqs_queue_name" {
  description = "Name of the main incident-triggers queue (modules/eventbridge's queue_name output) -- used for the 'oldest unprocessed message' alarm, a proxy for 'the SQS poller has stopped consuming.'"
  type        = string
}

variable "sqs_dlq_name" {
  description = "Name of the incident-triggers dead-letter queue (modules/eventbridge's dlq_name output). Any message here means max_receive_count was exceeded on a real incident trigger -- something a human needs to look at, not routine traffic. This is the alarm that closes the gap infra/README.md has flagged since the EventBridge chunk: nothing was watching this queue at all until now."
  type        = string
}

variable "alert_email" {
  description = "Email address to subscribe to the alerts SNS topic. No default -- if left null, the SNS topic and every alarm are still created (so `terraform plan`/`apply` work with zero setup), but nothing actually notifies anyone until a subscription exists. Set this, or subscribe manually, or wire up a different protocol (Slack via Lambda, PagerDuty, etc.) via the sns_topic_arn output before relying on these alarms for anything real."
  type        = string
  default     = null
}

variable "cpu_threshold_percent" {
  description = "ECS task CPUUtilization percent that triggers the high-CPU alarm, sustained for var.evaluation_periods consecutive 5-minute periods."
  type        = number
  default     = 80
}

variable "memory_threshold_percent" {
  description = "ECS task MemoryUtilization percent that triggers the high-memory alarm, same sustain window as CPU."
  type        = number
  default     = 80
}

variable "evaluation_periods" {
  description = "Consecutive 5-minute periods the ECS CPU/memory metrics must breach their threshold before alarming -- 3 periods (15 minutes) avoids paging on a brief spike from, e.g., a burst of incident classification calls."
  type        = number
  default     = 3
}

variable "dlq_message_threshold" {
  description = "Number of visible messages in the DLQ that triggers the alarm. Default 1 -- the DLQ should be empty in normal operation, so even a single message is worth a look, not something to wait for a batch of."
  type        = number
  default     = 1
}

variable "oldest_message_age_threshold_seconds" {
  description = "Seconds a message can sit unprocessed at the head of the main incident-triggers queue before alarming -- a proxy for 'the SQS poller has stopped consuming' (see backend/src/cloudops_ai/services/sqs_incident_poller.py). Default 600s (10 minutes) is well beyond the poller's normal long-poll/process cycle."
  type        = number
  default     = 600
}

variable "tags" {
  description = "Common tags applied to all resources in this module."
  type        = map(string)
  default     = {}
}
