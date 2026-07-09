output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.backend.name
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.backend.name
}

output "security_group_id" {
  value = aws_security_group.backend.id
}
