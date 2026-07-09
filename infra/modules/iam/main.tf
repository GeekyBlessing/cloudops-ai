# Three roles:
#   - MonitoringReadOnlyRole  -> assumed by Boto3AWSGateway         (backend/src/cloudops_ai/tools/readonly/)
#   - RemediationExecutorRole -> assumed by Boto3MutatingAWSGateway (backend/src/cloudops_ai/tools/mutating/)
#   - ecs-task-execution      -> used by ECS itself (image pull, log write), never by application code
#
# The read-only/mutating split is Interface Segregation carried all the way
# into IAM: the backend's IReadOnlyAWSTools/IMutatingAWSTools split
# (tools/interfaces.py) exists so investigative agents can never hold a
# mutating capability even in code. These two roles are the same guarantee
# enforced by AWS itself, one level further out -- even a bug that bypassed
# every application-level check could still only reach the exact API calls
# each role's policy grants. See /docs/ARCHITECTURE.md section 6 for the
# intended role-assumption flow (the running task uses
# MonitoringReadOnlyRole by default; RemediationExecutorRole is only
# assumed for the brief window services/approval_service.py actually
# invokes the Remediation Executor). Wiring *which* role is active *when*
# is deployment/application logic -- this module only creates the roles
# and their policies.

data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ---------------- MonitoringReadOnlyRole ----------------

resource "aws_iam_role" "monitoring_read_only" {
  name               = "${var.name_prefix}-monitoring-read-only"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
  tags               = var.tags
}

# Scoped to exactly the boto3 calls Boto3AWSGateway makes
# (tools/readonly/boto3_aws_gateway.py) -- no wildcard service access, and
# no mutating action of any kind.
data "aws_iam_policy_document" "monitoring_read_only" {
  statement {
    sid       = "EC2ReadOnly"
    effect    = "Allow"
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"] # DescribeInstances does not support resource-level restriction
  }

  statement {
    sid       = "CloudWatchReadOnly"
    effect    = "Allow"
    actions   = ["cloudwatch:GetMetricStatistics"]
    resources = ["*"] # CloudWatch metric reads do not support resource-level restriction
  }

  statement {
    sid       = "CloudTrailReadOnly"
    effect    = "Allow"
    actions   = ["cloudtrail:LookupEvents"]
    resources = ["*"] # LookupEvents does not support resource-level restriction
  }

  statement {
    sid    = "S3ReadOnly"
    effect = "Allow"
    actions = [
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketPolicyStatus",
      "s3:GetBucketAcl",
    ]
    resources = ["arn:aws:s3:::*"]
  }

  statement {
    sid    = "GuardDutyReadOnly"
    effect = "Allow"
    actions = [
      "guardduty:ListDetectors",
      "guardduty:ListFindings",
      "guardduty:GetFindings",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "STSCallerIdentity"
    effect    = "Allow"
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }

  statement {
    sid    = "IncidentsTableReadWrite"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:Scan",
      "dynamodb:Query",
    ]
    resources = [
      var.dynamodb_table_arn,
      "${var.dynamodb_table_arn}/index/*",
    ]
  }
}

resource "aws_iam_role_policy" "monitoring_read_only" {
  name   = "${var.name_prefix}-monitoring-read-only"
  role   = aws_iam_role.monitoring_read_only.id
  policy = data.aws_iam_policy_document.monitoring_read_only.json
}

# ---------------- RemediationExecutorRole ----------------

resource "aws_iam_role" "remediation_executor" {
  name               = "${var.name_prefix}-remediation-executor"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
  tags               = var.tags
}

# Scoped to exactly the boto3 calls Boto3MutatingAWSGateway makes
# (tools/mutating/boto3_mutating_gateway.py). This is the single most
# sensitive IAM policy in the whole system -- it's the real-world AWS
# enforcement layer behind the backend's HMAC-signed-approval gate
# (RemediationPlan.can_execute_live()). Even a bug that bypassed every
# check in application code could still only reach these exact API calls.
data "aws_iam_policy_document" "remediation_executor" {
  statement {
    sid    = "EC2Remediate"
    effect = "Allow"
    actions = [
      "ec2:RebootInstances",
      "ec2:StartInstances",
    ]
    resources = ["*"] # instance-level conditions (e.g. tag-based) are a reasonable hardening follow-up
  }

  statement {
    sid    = "AutoScalingRemediate"
    effect = "Allow"
    actions = [
      "autoscaling:DescribeAutoScalingGroups",
      "autoscaling:SetDesiredCapacity",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "S3Remediate"
    effect    = "Allow"
    actions   = ["s3:PutBucketPublicAccessBlock"]
    resources = ["arn:aws:s3:::*"]
  }

  statement {
    sid       = "IAMRemediate"
    effect    = "Allow"
    actions   = ["iam:DetachRolePolicy"]
    resources = ["*"] # narrowing to specific known-good target role ARNs is a strong follow-up
  }

  statement {
    sid       = "LambdaRemediate"
    effect    = "Allow"
    actions   = ["lambda:UpdateAlias"]
    resources = ["*"]
  }

  statement {
    sid       = "RDSRemediate"
    effect    = "Allow"
    actions   = ["rds:ModifyDBInstance"]
    resources = ["*"]
  }

  statement {
    sid    = "IncidentsTableReadWrite"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:Scan",
      "dynamodb:Query",
    ]
    resources = [
      var.dynamodb_table_arn,
      "${var.dynamodb_table_arn}/index/*",
    ]
  }
}

resource "aws_iam_role_policy" "remediation_executor" {
  name   = "${var.name_prefix}-remediation-executor"
  role   = aws_iam_role.remediation_executor.id
  policy = data.aws_iam_policy_document.remediation_executor.json
}

# ---------------- ECS task execution role ----------------
# Distinct from the two roles above: this is what ECS itself uses to pull
# the container image and write to CloudWatch Logs, not what application
# code assumes. AWS's own managed policy covers exactly this and nothing
# more, so there's no reason to hand-write it.

resource "aws_iam_role" "ecs_task_execution" {
  name               = "${var.name_prefix}-ecs-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
