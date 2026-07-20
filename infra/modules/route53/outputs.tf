output "zone_id" {
  description = "Route53 hosted zone ID. Used by the acm_certificate module for DNS validation records and by this environment's alias records pointing at CloudFront."
  value       = aws_route53_zone.this.zone_id
}

output "name_servers" {
  description = "The four name servers AWS assigned this zone. These must be set as the domain's nameservers at the registrar for DNS to actually resolve -- Terraform cannot do this step, since it happens outside AWS."
  value       = aws_route53_zone.this.name_servers
}
