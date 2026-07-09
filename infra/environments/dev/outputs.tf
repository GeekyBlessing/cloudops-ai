output "ecs_cluster_name" {
  value = module.ecs.cluster_name
}

output "ecs_service_name" {
  value = module.ecs.service_name
}

output "dynamodb_table_name" {
  value = module.dynamodb.table_name
}

output "monitoring_read_only_role_arn" {
  value = module.iam.monitoring_read_only_role_arn
}

output "remediation_executor_role_arn" {
  value = module.iam.remediation_executor_role_arn
}
