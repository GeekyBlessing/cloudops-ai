# infra/modules/frontend
#
# Hosts the built React dashboard in a private S3 bucket, served through a
# single CloudFront distribution. The distribution has two origins:
#
#   1. S3 (default behavior) -- the built dashboard (index.html, JS/CSS
#      bundles). Access is locked down to CloudFront only via Origin Access
#      Control (OAC); the bucket has no public access at all.
#   2. The ALB (ordered behaviors, one per var.api_path_patterns entry) --
#      every real backend route, proxied straight through with caching
#      disabled.
#
# Why one distribution with two origins, instead of hosting the dashboard
# separately and calling the ALB directly from the browser: CloudFront
# terminates TLS with its own default *.cloudfront.net certificate, but the
# ALB (infra/modules/alb) only has an HTTP:80 listener -- there's no ACM
# certificate because there's no custom domain yet (see infra/README.md's
# "Explicitly deferred" section). If the dashboard called the ALB directly,
# every API request from the HTTPS-served dashboard to the HTTP-only ALB
# would be blocked by the browser as mixed content, and the app would load
# but not function. Routing API paths through CloudFront too means the
# browser only ever talks to CloudFront over HTTPS; the plaintext HTTP hop
# is CloudFront-to-ALB, inside AWS's own network, not over the public
# internet.

data "aws_caller_identity" "current" {}

locals {
  # S3 bucket names are globally unique across every AWS account, unlike
  # everything else this project has named so far (DynamoDB tables, ECR
  # repos, etc. are only unique within an account/region) -- the account ID
  # suffix avoids a collision with some other AWS account that happened to
  # pick the same name_prefix.
  bucket_name  = "${var.name_prefix}-frontend-${data.aws_caller_identity.current.account_id}"
  s3_origin_id  = "${var.name_prefix}-s3"
  alb_origin_id = "${var.name_prefix}-alb"
}

# ---------------------------------------------------------------------------
# S3 bucket: private, CloudFront-only access via OAC
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "frontend" {
  bucket = local.bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

data "aws_iam_policy_document" "frontend_bucket" {
  statement {
    sid       = "AllowCloudFrontServicePrincipalReadOnly"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.this.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = data.aws_iam_policy_document.frontend_bucket.json
}

# ---------------------------------------------------------------------------
# CloudFront: Origin Access Control for the S3 origin
# ---------------------------------------------------------------------------

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${var.name_prefix}-frontend-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ---------------------------------------------------------------------------
# CloudFront Function: SPA client-side-routing fallback
#
# Only attached to the S3 (default) behavior. Deliberately NOT implemented
# as a distribution-wide custom_error_response, because
# custom_error_response is keyed by HTTP status code across the whole
# distribution -- a 404 from the ALB origin (a real "incident not found"
# from the backend) would also get rewritten to index.html, silently
# turning real API errors into a 200 response containing the SPA shell.
# A function scoped to one behavior avoids that entirely.
# ---------------------------------------------------------------------------

resource "aws_cloudfront_function" "spa_fallback" {
  name    = "${var.name_prefix}-spa-fallback"
  runtime = "cloudfront-js-1.0"
  comment = "Rewrites requests with no file extension to /index.html so React Router can handle client-side routes. Associated with the S3 behavior only."
  publish = true
  code    = <<-EOT
    function handler(event) {
      var request = event.request;
      var uri = request.uri;

      if (uri.includes('.')) {
        return request;
      }

      request.uri = '/index.html';
      return request;
    }
  EOT
}

# ---------------------------------------------------------------------------
# CloudFront managed policies (cache + origin request behavior)
# ---------------------------------------------------------------------------

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewer"
}

# ---------------------------------------------------------------------------
# CloudFront distribution
# ---------------------------------------------------------------------------

resource "aws_cloudfront_distribution" "this" {
  enabled             = true
  default_root_object = var.default_root_object
  price_class         = var.price_class
  comment             = "${var.name_prefix} dashboard"

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = local.s3_origin_id
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  origin {
    domain_name = var.alb_dns_name
    origin_id   = local.alb_origin_id

    custom_origin_config {
      http_port              = 80
      https_port              = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods          = ["GET", "HEAD"]
    target_origin_id        = local.s3_origin_id
    viewer_protocol_policy  = "redirect-to-https"
    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_optimized.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_fallback.arn
    }
  }

  dynamic "ordered_cache_behavior" {
    for_each = var.api_path_patterns
    content {
      path_pattern              = ordered_cache_behavior.value
      allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
      cached_methods              = ["GET", "HEAD"]
      target_origin_id           = local.alb_origin_id
      viewer_protocol_policy     = "redirect-to-https"
      cache_policy_id             = data.aws_cloudfront_cache_policy.caching_disabled.id
      origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer.id
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = var.tags
}
