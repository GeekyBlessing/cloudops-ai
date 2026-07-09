provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "cloudops-ai"
      Environment = "dev"
      ManagedBy   = "terraform"
    }
  }
}
