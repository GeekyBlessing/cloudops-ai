# CloudWatch alarms + dashboard for the backend's own operational health --
# not to be confused with modules/eventbridge, which routes CloudWatch
# Alarms (on *other* AWS resources the backend investigates, plus
# GuardDuty findings) into the incident pipeline as input. These alarms
# are about this project's own infra: is the ECS task healthy, and -- the
# gap infra/README.md has flagged since the EventBridge chunk -- is
# anything actually watching the incident-triggers dead-letter queue.
# Nothing did, until this module.

data "aws_region" "current" {}

resource "aws_sns_topic" "alerts" {
  name = "${var.name_prefix}-alerts"
  tags = var.tags
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count = var.alert_email == null ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "ecs_cpu_high" {
  alarm_name          = "${var.name_prefix}-ecs-cpu-high"
  alarm_description   = "Backend ECS task CPUUtilization above ${var.cpu_threshold_percent}% for ${var.evaluation_periods} consecutive periods."
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = var.evaluation_periods
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.cpu_threshold_percent
  treat_missing_data  = "missing"

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
  tags          = var.tags
}

resource "aws_cloudwatch_metric_alarm" "ecs_memory_high" {
  alarm_name          = "${var.name_prefix}-ecs-memory-high"
  alarm_description   = "Backend ECS task MemoryUtilization above ${var.memory_threshold_percent}% for ${var.evaluation_periods} consecutive periods."
  namespace           = "AWS/ECS"
  metric_name         = "MemoryUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = var.evaluation_periods
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.memory_threshold_percent
  treat_missing_data  = "missing"

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
  tags          = var.tags
}

# The alarm this chunk exists for: previously nothing watched the DLQ at
# all. Any message here means an incident trigger was received
# max_receive_count times (modules/eventbridge's max_receive_count,
# default 3) without the poller successfully processing it -- a real
# failure, not routine traffic, so even a single message alarms rather
# than waiting for a batch.
resource "aws_cloudwatch_metric_alarm" "dlq_has_messages" {
  alarm_name          = "${var.name_prefix}-incident-triggers-dlq-depth"
  alarm_description   = "One or more messages in the incident-triggers dead-letter queue -- the SQS poller failed to process a real incident trigger max_receive_count times."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = var.dlq_message_threshold
  # An empty DLQ reports no data points at all, not a zero -- CloudWatch
  # doesn't publish SQS metrics for a queue with no activity. That absence
  # means "nothing to alarm on," not "something's wrong," so missing data
  # must not breach.
  treat_missing_data = "notBreaching"

  dimensions = {
    QueueName = var.sqs_dlq_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
  tags          = var.tags
}

# A proxy for "the SQS poller has stopped consuming" -- if the oldest
# message at the head of the main queue has been sitting for longer than
# the poller's normal long-poll/process cycle should ever take, either the
# poller process is down or it's stuck. Same missing-data reasoning as the
# DLQ alarm above: no messages in flight means no data points, not zero.
resource "aws_cloudwatch_metric_alarm" "queue_oldest_message_age" {
  alarm_name          = "${var.name_prefix}-incident-triggers-oldest-message-age"
  alarm_description   = "Oldest unprocessed message in the incident-triggers queue has been waiting longer than ${var.oldest_message_age_threshold_seconds}s -- the SQS poller may have stopped consuming."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.oldest_message_age_threshold_seconds
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = var.sqs_queue_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
  tags          = var.tags
}

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = "${var.name_prefix}-backend"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "ECS CPU / Memory Utilization"
          view    = "timeSeries"
          stacked = false
          period  = 300
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", var.ecs_service_name, { label = "CPU %" }],
            ["AWS/ECS", "MemoryUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", var.ecs_service_name, { label = "Memory %" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Incident Trigger Queue Depth"
          view    = "timeSeries"
          stacked = false
          period  = 300
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.sqs_queue_name, { label = "Main queue" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.sqs_dlq_name, { label = "DLQ" }],
          ]
        }
      },
      {
        type   = "alarm"
        x      = 0
        y      = 6
        width  = 24
        height = 4
        properties = {
          title = "Alarm status"
          alarms = [
            aws_cloudwatch_metric_alarm.ecs_cpu_high.arn,
            aws_cloudwatch_metric_alarm.ecs_memory_high.arn,
            aws_cloudwatch_metric_alarm.dlq_has_messages.arn,
            aws_cloudwatch_metric_alarm.queue_oldest_message_age.arn,
          ]
        }
      },
    ]
  })
}
