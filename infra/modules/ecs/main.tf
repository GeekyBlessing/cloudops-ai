# Minimal Fargate deployment: no ALB, no custom VPC -- the task runs in the
# account's default VPC/subnets with a public IP, which is enough to prove
# "this runs as a real container in real AWS" for a portfolio project. A
# production deployment needs an ALB (stable DNS name, TLS termination) and
# a purpose-built VPC (private subnets for the task, a NAT gateway or VPC
# endpoints for outbound AWS API calls) -- both are explicitly out of scope
# for this module and tracked as a follow-up in infra/README.md, not
# silently skipped.

data "aws_region" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "backend" {
  name        = "${var.name_prefix}-backend"
  description = "CloudOps AI backend task -- inbound API traffic, unrestricted outbound for AWS API calls"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "API traffic"
    from_port   = var.container_port
    to_port     = var.container_port
    protocol    = "tcp"
    # Open to the internet for portfolio-demo simplicity -- a production
    # deployment would restrict this to an ALB security group instead of
    # exposing the task directly. See module docstring above.
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${var.name_prefix}-backend"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_ecs_cluster" "this" {
  name = "${var.name_prefix}-cluster"
  tags = var.tags
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "${var.name_prefix}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  task_role_arn            = var.task_role_arn
  execution_role_arn       = var.execution_role_arn

  container_definitions = jsonencode([
    {
      name      = "backend"
      image     = var.container_image
      essential = true
      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]
      environment = var.environment
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.backend.name
          "awslogs-region"        = data.aws_region.current.name
          "awslogs-stream-prefix" = "backend"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "backend" {
  name            = "${var.name_prefix}-backend"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.backend.id]
    assign_public_ip = true
  }

  tags = var.tags
}
