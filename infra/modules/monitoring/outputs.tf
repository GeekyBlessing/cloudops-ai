output "sns_topic_arn" {
  description = "Subscribe additional protocols (SMS, another email, a Lambda that forwards to Slack, etc.) to this topic beyond the single optional var.alert_email subscription this module already creates."
  value       = aws_sns_topic.alerts.arn
}

output "dashboard_name" {
  value = aws_cloudwatch_dashboard.this.dashboard_name
}

output "dashboard_url" {
  description = "Direct console URL -- CloudWatch dashboard URLs aren't exposed as a resource attribute, so this is constructed from the current region and dashboard name."
  value       = "https://${data.aws_region.current.name}.console.aws.amazon.com/cloudwatch/home?region=${data.aws_region.current.name}#dashboards:name=${aws_cloudwatch_dashboard.this.dashboard_name}"
}
