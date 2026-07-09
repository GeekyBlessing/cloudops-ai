output "table_name" {
  description = "Name of the created Incidents table -- feed into CLOUDOPS_DYNAMODB_TABLE_INCIDENTS."
  value       = aws_dynamodb_table.incidents.name
}

output "table_arn" {
  description = "ARN of the Incidents table -- used to scope the IAM policies granted to the ECS task roles."
  value       = aws_dynamodb_table.incidents.arn
}
