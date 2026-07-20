# CloudFront only accepts ACM certificates issued in us-east-1, regardless
# of which region the rest of the stack runs in. This module always needs
# a us-east-1 provider passed in explicitly by the caller, in addition to
# the default provider (used for the Route53 validation records, which
# aren't region-scoped).
terraform {
  required_providers {
    aws = {
      source                = "hashicorp/aws"
      configuration_aliases = [aws.us_east_1]
    }
  }
}
