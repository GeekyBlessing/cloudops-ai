output "certificate_arn" {
  description = "ARN of the validated ACM certificate, ready to attach to a CloudFront distribution as viewer_certificate.acm_certificate_arn."
  value       = aws_acm_certificate_validation.this.certificate_arn
}
