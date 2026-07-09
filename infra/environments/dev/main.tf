# Dev environment: wires the dynamodb, iam, and ecs modules together into
# one deployable stack. This is intentionally the *only* environment
# provided so far -- staging/ and demo-live/ (the environment PROJECT_STRUCTURE.md
# describes as the only one ever permitted to run with
# CLOUDOPS_REMEDIATION_MODE=live) are follow-ups once this one is proven
# out, not because they're architecturally different, but because copying
# this environment's shape twice more with different tfvars is mechanical
# work that isn't worth doing before the first one has actually been
# applied against a real account.

locals {
  name_prefix = "cloudops-ai-dev"
  tags = {
    Project     = "cloudops-ai"
    Environment = "dev"
  }
}

module "dynamodb" {
  source = "../../modules/dynamodb"

  table_name = "cloudops-ai-incidents"
  tags       = local.tags
}

module "iam" {
  source = "../../modules/iam"

  name_prefix        = local.name_prefix
  dynamodb_table_arn = module.dynamodb.table_arn
  tags               = local.tags
}

module "ecs" {
  source = "../../modules/ecs"

  name_prefix         = local.name_prefix
  container_image     = var.container_image
  task_role_arn       = module.iam.ecs_task_role_arn
  execution_role_arn  = module.iam.ecs_task_execution_role_arn
  desired_count       = var.desired_count

  # Mirrors core/config.py's Settings field names exactly (CLOUDOPS_ prefix
  # + upper-snake-case of the field name) -- see backend/src/cloudops_ai/core/config.py.
  environment = [
    { name = "CLOUDOPS_USE_DYNAMODB", value = "true" },
    { name = "CLOUDOPS_DYNAMODB_TABLE_INCIDENTS", value = module.dynamodb.table_name },
    { name = "CLOUDOPS_USE_REAL_AWS", value = "true" },
    { name = "CLOUDOPS_AWS_REGION", value = var.aws_region },
    # Dry-run by default here too, same as the application-level default in
    # core/config.py -- an environment variable is exactly the kind of
    # thing that's easy to typo or leave unset, so the infra-level default
    # matches the code-level fail-safe default rather than assuming
    # whoever deploys this will always remember to set it explicitly.
    { name = "CLOUDOPS_REMEDIATION_MODE", value = "dry_run" },
    { name = "CLOUDOPS_LOG_LEVEL", value = "INFO" },
  ]

  tags = local.tags
}
