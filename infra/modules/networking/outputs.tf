output "vpc_id" {
  value = aws_vpc.this.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Where modules/ecs now places the backend task -- see modules/ecs's subnet_ids variable."
  value       = aws_subnet.private[*].id
}
