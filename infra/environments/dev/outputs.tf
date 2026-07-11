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
output "cloudfront_domain_name" {
  description = "Single HTTPS URL the dashboard is reachable at (SPA + API, both proxied through this one CloudFront distribution)."
  value       = module.frontend.cloudfront_domain_name
}

output "frontend_bucket_name" {
  description = "S3 bucket holding the built dashboard. Used by deploy.yml's `aws s3 sync` step."
  value       = module.frontend.bucket_name
}

output "frontend_bucket_arn" {
  description = "S3 bucket ARN. Used to scope the CI deploy role's S3 permissions."
  value       = module.frontend.bucket_arn
}

output "frontend_cloudfront_distribution_id" {
  description = "CloudFront distribution ID. Used by deploy.yml's cache-invalidation step."
  value       = module.frontend.cloudfront_distribution_id
}

output "frontend_cloudfront_distribution_arn" {
  description = "CloudFront distribution ARN. Used to scope the CI deploy role's cloudfront:CreateInvalidation permission."
  value       = module.frontend.cloudfront_distribution_arn
}
