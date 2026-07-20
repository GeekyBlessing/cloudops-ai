# infra/modules/route53
#
# Public hosted zone for the project's custom domain. This is intentionally
# a separate, minimal module -- creating a hosted zone is a one-time,
# semi-manual action (the returned name servers have to be copied into the
# domain's registrar once), unlike everything else in this repo that's
# fully automated end-to-end.
resource "aws_route53_zone" "this" {
  name    = var.domain_name
  comment = "Public hosted zone for ${var.domain_name}, managed by Terraform (cloudops-ai)."
  tags    = var.tags
}
