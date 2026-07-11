output "bucket_name" {
  description = "Name of the S3 bucket holding the built dashboard. Used by deploy.yml for `aws s3 sync`."
  value       = aws_s3_bucket.frontend.bucket
}

output "bucket_arn" {
  description = "ARN of the S3 bucket. Used to scope the CI deploy role's S3 permissions."
  value       = aws_s3_bucket.frontend.arn
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID. Used by deploy.yml for cache invalidation after each deploy."
  value       = aws_cloudfront_distribution.this.id
}

output "cloudfront_distribution_arn" {
  description = "CloudFront distribution ARN. Used to scope the CI deploy role's cloudfront:CreateInvalidation permission."
  value       = aws_cloudfront_distribution.this.arn
}

output "cloudfront_domain_name" {
  description = "CloudFront's default *.cloudfront.net domain. This is the single URL the dashboard is reachable at -- both the SPA and the API (proxied to the ALB) live under this one HTTPS origin."
  value       = aws_cloudfront_distribution.this.domain_name
}
