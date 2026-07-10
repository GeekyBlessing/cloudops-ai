# Application Load Balancer fronting the backend -- the piece that lets
# modules/ecs move the task into private subnets with no public IP.
# HTTP only, no TLS: a real certificate needs a real domain name (ACM
# DNS validation), and this project doesn't have one -- see
# infra/README.md's "Explicitly deferred" section. Everything through
# this ALB is plaintext, same as the direct-public-IP setup it replaces
# was (that had no TLS either); this is a reachability and exposure-surface
# improvement, not a TLS one.

resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb"
  description = "CloudOps AI ALB -- public inbound on the listener port, unrestricted outbound to reach the backend task"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidr_blocks
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_lb" "this" {
  name               = "${var.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids

  tags = var.tags
}

resource "aws_lb_target_group" "backend" {
  name        = "${var.name_prefix}-backend"
  port        = var.target_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  # Fargate tasks in awsvpc network mode register by IP, not by EC2
  # instance ID -- "ip" is the only target type that works here.
  target_type = "ip"

  health_check {
    path                = var.health_check_path
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = var.tags
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }
}
