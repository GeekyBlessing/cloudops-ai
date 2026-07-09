output "repository_url" {
  description = "Full URI (no tag) for the backend repository, e.g. '<account>.dkr.ecr.<region>.amazonaws.com/cloudops-ai-dev-backend'. Combine with a tag (deploy.yml uses the git SHA) to get a full image reference."
  value       = aws_ecr_repository.backend.repository_url
}

output "repository_name" {
  value = aws_ecr_repository.backend.name
}
