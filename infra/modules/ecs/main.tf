# Fargate deployment behind an ALB (modules/alb) in private subnets
# (modules/networking): the task itself has no public IP and is not
# directly reachable from the internet -- only the ALB is. This replaces
# the earlier public-subnet-with-a-public-IP setup, which was fine for
# proving "this runs as a real container in real AWS" but exposed the raw
# container port directly. TLS/HTTPS still isn't in scope (no domain name
# to get an ACM certificate for) -- see infra/README.md.

data "aws_region" "current" {}

resource "aws_security_group" "backend" {
  name        = "${var.name_prefix}-backend"
  description = "CloudOps AI backend task -- inbound API traffic from the ALB only, unrestricted outbound for AWS API calls"
  vpc_id      = var.vpc_id

  ingress {
    description = "API traffic from the ALB only"
    from_port   = var.container_port
    to_port     = var.container_port
    protocol    = "tcp"
    # Sourced from the ALB's own security group, not a CIDR block -- the
    # task is in a private subnet with no public IP, so the ALB is the
    # only thing that can reach it inbound at all. This is the "put an
    # ALB security group here instead" this module's docstring used to
    # describe as a future improvement; it's built now.
    security_groups = [var.alb_security_group_id]
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

  # Gives a newly-started task time to actually come up (image pull +
  # app startup) before the ALB's health check failures start counting
  # against it -- without this, a slow-starting task can get marked
  # unhealthy and cycled before it ever gets a chance to pass a check.
  health_check_grace_period_seconds = var.health_check_grace_period_seconds

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "backend"
    container_port   = var.container_port
  }

  network_configuration {
    subnets         = var.subnet_ids
    security_groups = [aws_security_group.backend.id]
    # False now that the task lives in a private subnet (modules/networking)
    # and is fronted by modules/alb -- it doesn't need, and shouldn't have,
    # a public IP of its own anymore.
    assign_public_ip = false
  }

  tags = var.tags
}
