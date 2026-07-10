output "alb_dns_name" {
  description = "Stable DNS name for the backend -- this is the address that stops changing on every redeploy, unlike the public IP the task used to get directly. Point frontend/.env.local's VITE_API_BASE_URL at http://<this value> once applied."
  value       = aws_lb.this.dns_name
}

output "alb_security_group_id" {
  description = "Feeds modules/ecs's security group -- the backend task's ingress rule allows traffic from this security group, not from any CIDR block."
  value       = aws_security_group.alb.id
}

output "target_group_arn" {
  description = "Feeds modules/ecs's aws_ecs_service load_balancer block, so the ECS service registers/deregisters tasks against this target group as they start and stop."
  value       = aws_lb_target_group.backend.arn
}

output "listener_arn" {
  description = "Not consumed directly by any other module -- exists so environments/dev can express an explicit dependency (module.ecs depends_on module.alb) ensuring the listener exists before the ECS service tries to register tasks against the target group."
  value       = aws_lb_listener.http.arn
}
