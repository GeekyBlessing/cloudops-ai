output "queue_url" {
  description = "URL the backend's SQS poller connects to (CLOUDOPS_SQS_QUEUE_URL)."
  value       = aws_sqs_queue.incident_triggers.id
}

output "queue_arn" {
  description = "Feeds into modules/iam so the ECS task role can be granted consume permissions on exactly this queue."
  value       = aws_sqs_queue.incident_triggers.arn
}

output "queue_name" {
  description = "Feeds modules/monitoring's SQS alarm dimensions -- CloudWatch's AWS/SQS metrics are dimensioned by QueueName, not ARN or URL."
  value       = aws_sqs_queue.incident_triggers.name
}

output "dlq_url" {
  value = aws_sqs_queue.incident_triggers_dlq.id
}

output "dlq_name" {
  description = "Feeds modules/monitoring's DLQ depth alarm -- see queue_name's description for why QueueName specifically."
  value       = aws_sqs_queue.incident_triggers_dlq.name
}
