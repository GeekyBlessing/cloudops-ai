provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "cloudops-ai"
      Environment = "demo-live"
      ManagedBy   = "terraform"
    }
  }
}

# CloudFront only accepts ACM certificates issued in us-east-1. The rest of
# this environment's resources use var.aws_region; this aliased provider
# exists solely so the acm_certificate module can request/validate a
# certificate in the right region regardless of what var.aws_region is.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = {
      Project     = "cloudops-ai"
      Environment = "demo-live"
      ManagedBy   = "terraform"
    }
  }
}
