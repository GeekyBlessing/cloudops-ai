# Demo-live environment: identical shape to environments/dev and
# environments/staging, except CLOUDOPS_REMEDIATION_MODE is hardcoded to
# "live" below -- the only environment PROJECT_STRUCTURE.md ever permits
# to run with live remediation enabled. Hardcoded directly in this file's
# ecs module block, not exposed as a variable any environment could
# accidentally be passed at apply time -- see infra/README.md's "Three
# environments" section for the reasoning.

locals {
  name_prefix = "cloudops-ai-demo-live"
  tags = {
    Project     = "cloudops-ai"
    Environment = "demo-live"
  }
}

module "networking" {
  source = "../../modules/networking"

  name_prefix = local.name_prefix
  tags        = local.tags
}

module "alb" {
  source = "../../modules/alb"

  name_prefix       = local.name_prefix
  vpc_id            = module.networking.vpc_id
  public_subnet_ids = module.networking.public_subnet_ids
  tags              = local.tags
}

module "dynamodb" {
  source = "../../modules/dynamodb"

  table_name = "cloudops-ai-incidents"
  tags       = local.tags
}

module "ecr" {
  source = "../../modules/ecr"

  name_prefix = local.name_prefix
  tags        = local.tags
}

module "eventbridge" {
  source = "../../modules/eventbridge"

  name_prefix = local.name_prefix
  tags        = local.tags
}

module "iam" {
  source = "../../modules/iam"

  name_prefix        = local.name_prefix
  dynamodb_table_arn = module.dynamodb.table_arn
  sqs_queue_arn       = module.eventbridge.queue_arn
  tags                = local.tags
}

module "ecs" {
  source = "../../modules/ecs"

  name_prefix = local.name_prefix
  # Built from the ECR module's own output rather than accepting an
  # arbitrary external URI -- ties the deployed image directly to the
  # repository this stack actually owns and manages the lifecycle policy
  # for, instead of trusting a caller to pass a URI that happens to point
  # at the right place.
  container_image    = "${module.ecr.repository_url}:${var.image_tag}"
  vpc_id              = module.networking.vpc_id
  subnet_ids          = module.networking.private_subnet_ids
  alb_security_group_id = module.alb.alb_security_group_id
  target_group_arn      = module.alb.target_group_arn
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
    { name = "CLOUDOPS_REMEDIATION_MODE", value = "live" },
    { name = "CLOUDOPS_LOG_LEVEL", value = "INFO" },
    { name = "CLOUDOPS_SQS_QUEUE_URL", value = module.eventbridge.queue_url },
  ]

  tags = local.tags

  # The service's load_balancer block references module.alb's target
  # group ARN, which Terraform already tracks as a dependency -- but that
  # alone doesn't guarantee the *listener* exists yet, and ECS can fail to
  # register the first task if it doesn't. Depending on the whole module
  # forces every ALB resource, including the listener, to exist first.
  depends_on = [module.alb]
}

module "monitoring" {
  source = "../../modules/monitoring"

  name_prefix      = local.name_prefix
  ecs_cluster_name = module.ecs.cluster_name
  ecs_service_name = module.ecs.service_name
  sqs_queue_name   = module.eventbridge.queue_name
  sqs_dlq_name     = module.eventbridge.dlq_name
  alert_email      = var.alert_email
  tags             = local.tags
}
module "route53" {
  source      = "../../modules/route53"
  domain_name = local.domain_name
  tags        = local.tags
}

module "acm_certificate" {
  source = "../../modules/acm_certificate"
  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }
  domain_name                = local.domain_name
  subject_alternative_names  = ["www.${local.domain_name}"]
  zone_id                    = module.route53.zone_id
  tags                       = local.tags
}

module "frontend" {
  source              = "../../modules/frontend"
  name_prefix         = local.name_prefix
  alb_dns_name        = module.alb.alb_dns_name
  aliases             = [local.domain_name, "www.${local.domain_name}"]
  acm_certificate_arn = module.acm_certificate.certificate_arn
  tags                = local.tags
}

# CloudFront's alias target hosted zone ID is the same fixed value
# ("Z2FDTNDATAQYW2") for every CloudFront distribution -- this isn't
# specific to this project, it's how Route53 alias records address any
# CloudFront distribution.
resource "aws_route53_record" "apex" {
  zone_id = module.route53.zone_id
  name    = local.domain_name
  type    = "A"
  alias {
    name                   = module.frontend.cloudfront_domain_name
    zone_id                = "Z2FDTNDATAQYW2"
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "apex_ipv6" {
  zone_id = module.route53.zone_id
  name    = local.domain_name
  type    = "AAAA"
  alias {
    name                   = module.frontend.cloudfront_domain_name
    zone_id                = "Z2FDTNDATAQYW2"
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "www" {
  zone_id = module.route53.zone_id
  name    = "www.${local.domain_name}"
  type    = "A"
  alias {
    name                   = module.frontend.cloudfront_domain_name
    zone_id                = "Z2FDTNDATAQYW2"
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "www_ipv6" {
  zone_id = module.route53.zone_id
  name    = "www.${local.domain_name}"
  type    = "AAAA"
  alias {
    name                   = module.frontend.cloudfront_domain_name
    zone_id                = "Z2FDTNDATAQYW2"
    evaluate_target_health = false
  }
}


locals {
  domain_name = "cloudops-ai.dev"
}
