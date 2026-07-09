output "queue_url" {
  description = "URL the backend's SQS poller connects to (CLOUDOPS_SQS_QUEUE_URL)."
  value       = aws_sqs_queue.incident_triggers.id
}

output "queue_arn" {
  description = "Feeds into modules/iam so the ECS task role can be granted consume permissions on exactly this queue."
  value       = aws_sqs_queue.incident_triggers.arn
}

output "dlq_url" {
  value = aws_sqs_queue.incident_triggers_dlq.id
}
