# Routes real AWS signals into the incident pipeline: CloudWatch Alarms
# transitioning to ALARM state, and GuardDuty findings at or above a
# severity threshold, both land on one SQS queue that the backend's
# services/sqs_incident_poller.py long-polls.
#
# Why SQS and not, say, a Lambda that calls POST /incidents directly: the
# ECS service (modules/ecs) has no ALB and no stable DNS name -- its public
# IP changes on every redeploy (see infra/README.md's "Explicitly
# deferred" section). A Lambda calling a moving HTTP target would break on
# every deploy. SQS sidesteps that entirely: the backend polls the queue
# using its own IAM role, so nothing external needs to know the task's
# current address at all. This is also the shape /docs/ARCHITECTURE.md
# originally specified (EventBridge -> SQS -> ECS), not a deviation from
# it.

resource "aws_sqs_queue" "incident_triggers_dlq" {
  name                      = "${var.name_prefix}-incident-triggers-dlq"
  message_retention_seconds = 1209600 # 14 days -- DLQ messages need longer retention than the main queue since they represent something that needs human investigation, not routine processing
  tags                      = var.tags
}

resource "aws_sqs_queue" "incident_triggers" {
  name                       = "${var.name_prefix}-incident-triggers"
  message_retention_seconds = var.message_retention_seconds
  visibility_timeout_seconds = var.visibility_timeout_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.incident_triggers_dlq.arn
    maxReceiveCount      = var.max_receive_count
  })

  tags = var.tags
}

# EventBridge needs explicit permission to deliver to an SQS queue --
# unlike Lambda targets, EventBridge->SQS is not implicitly allowed just by
# creating an aws_cloudwatch_event_target. Scoped via aws:SourceArn to
# exactly these two rules, not "any rule in this account," so no other
# EventBridge rule anyone creates later can silently start writing to this
# queue.
data "aws_iam_policy_document" "incident_triggers_queue_policy" {
  statement {
    sid    = "AllowEventBridgeSend"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.incident_triggers.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values = [
        aws_cloudwatch_event_rule.cloudwatch_alarms.arn,
        aws_cloudwatch_event_rule.guardduty_findings.arn,
      ]
    }
  }
}

resource "aws_sqs_queue_policy" "incident_triggers" {
  queue_url = aws_sqs_queue.incident_triggers.id
  policy    = data.aws_iam_policy_document.incident_triggers_queue_policy.json
}

# CloudWatch Alarms emit "CloudWatch Alarm State Change" events to the
# default EventBridge bus automatically, no SNS topic or subscription
# needed -- filtered to ALARM transitions only, so recovery (OK) and
# INSUFFICIENT_DATA transitions don't create incidents for something that
# already resolved itself or never had enough data to say either way.
resource "aws_cloudwatch_event_rule" "cloudwatch_alarms" {
  name        = "${var.name_prefix}-cloudwatch-alarm-state-change"
  description = "Routes CloudWatch Alarms entering ALARM state to the incident triggers queue"

  event_pattern = jsonencode({
    source      = ["aws.cloudwatch"]
    detail-type = ["CloudWatch Alarm State Change"]
    detail = {
      state = {
        value = ["ALARM"]
      }
    }
  })

  tags = var.tags
}

resource "aws_cloudwatch_event_target" "cloudwatch_alarms_to_sqs" {
  rule      = aws_cloudwatch_event_rule.cloudwatch_alarms.name
  target_id = "incident-triggers-queue"
  arn       = aws_sqs_queue.incident_triggers.arn
}

# GuardDuty findings also emit natively to the default EventBridge bus.
# Filtered by severity using EventBridge's numeric matching -- see
# guardduty_severity_threshold's description for why 4.0 specifically.
resource "aws_cloudwatch_event_rule" "guardduty_findings" {
  name        = "${var.name_prefix}-guardduty-finding"
  description = "Routes GuardDuty findings at or above the severity threshold to the incident triggers queue"

  event_pattern = jsonencode({
    source      = ["aws.guardduty"]
    detail-type = ["GuardDuty Finding"]
    detail = {
      severity = [{ numeric = [">=", var.guardduty_severity_threshold] }]
    }
  })

  tags = var.tags
}

resource "aws_cloudwatch_event_target" "guardduty_findings_to_sqs" {
  rule      = aws_cloudwatch_event_rule.guardduty_findings.name
  target_id = "incident-triggers-queue"
  arn       = aws_sqs_queue.incident_triggers.arn
}
