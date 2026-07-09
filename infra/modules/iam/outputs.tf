output "monitoring_read_only_role_arn" {
  description = "ARN of MonitoringReadOnlyRole -- the role Boto3AWSGateway is intended to assume."
  value       = aws_iam_role.monitoring_read_only.arn
}

output "remediation_executor_role_arn" {
  description = "ARN of RemediationExecutorRole -- the role Boto3MutatingAWSGateway is intended to assume."
  value       = aws_iam_role.remediation_executor.arn
}

output "ecs_task_execution_role_arn" {
  description = "ARN of the ECS task execution role -- feeds into the ECS task definition's execution_role_arn."
  value       = aws_iam_role.ecs_task_execution.arn
}

output "ecs_task_role_arn" {
  description = "Default task role bound to the ECS task definition -- MonitoringReadOnlyRole, since read-only investigation is the common-case workload. The Remediation Executor's brief mutating window is a deliberate exception handled at the application/deployment level, not the task's default identity -- see this module's main.tf docstring."
  value       = aws_iam_role.monitoring_read_only.arn
}
