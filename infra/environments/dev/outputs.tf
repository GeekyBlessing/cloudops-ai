output "vpc_id" {
  value = module.networking.vpc_id
}

output "alb_dns_name" {
  description = "The backend's stable public address -- point frontend/.env.local's VITE_API_BASE_URL at http://<this value>. Replaces the old floating task public IP, which changed on every redeploy."
  value       = module.alb.alb_dns_name
}

output "ecs_cluster_name" {
  value = module.ecs.cluster_name
}

output "ecs_service_name" {
  value = module.ecs.service_name
}

output "dynamodb_table_name" {
  value = module.dynamodb.table_name
}

output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "sqs_queue_url" {
  value = module.eventbridge.queue_url
}

output "monitoring_read_only_role_arn" {
  value = module.iam.monitoring_read_only_role_arn
}

output "remediation_executor_role_arn" {
  value = module.iam.remediation_executor_role_arn
}

output "monitoring_dashboard_url" {
  value = module.monitoring.dashboard_url
}

output "monitoring_sns_topic_arn" {
  value = module.monitoring.sns_topic_arn
}
