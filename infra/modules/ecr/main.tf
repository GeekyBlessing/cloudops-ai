# A single ECR repository for the backend container image.
#
# Scoped to backend only, deliberately -- there's no ECS service or
# S3+CloudFront distribution for the frontend yet (see infra/README.md's
# "Explicitly deferred" section), so a frontend registry would sit unused.
# Add a second aws_ecr_repository here when frontend hosting is actually
# built, rather than provisioning storage for an image nothing deploys.
resource "aws_ecr_repository" "backend" {
  name = "${var.name_prefix}-backend"

  # Automatically scans each pushed image for known OS/package
  # vulnerabilities (via Amazon Inspector) -- catching a vulnerable base
  # image is far cheaper to fix at push time than after it's running in
  # Fargate.
  image_scanning_configuration {
    scan_on_push = true
  }

  # Immutable tags: once "abc123f" (a git SHA) is pushed, that tag can
  # never be overwritten with different image content. This matters
  # specifically because deploy.yml tags images with the git SHA that
  # triggered the build -- if tags were mutable, "what's actually running"
  # could silently drift from "what that SHA's code looked like."
  image_tag_mutability = "IMMUTABLE"

  tags = var.tags
}

# Untagged images accumulate from failed/superseded builds (e.g. a push
# that completed layer upload but never got tagged due to a later step
# failing) -- without this, ECR storage costs grow unbounded over time.
# This only ever targets untagged images; anything with a real tag
# (a deployed git SHA) is retained forever, since IMMUTABLE tags mean we
# can never be sure an old tag isn't still referenced by a running task
# definition somewhere.
resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after ${var.untagged_image_expiry_days} days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.untagged_image_expiry_days
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
