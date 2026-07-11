terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state -- see infra/README.md for the one-time bootstrap steps
  # (creating the S3 bucket + DynamoDB lock table this block points at)
  # that have to happen *before* it can be uncommented and `terraform
  # init` run against it. Left commented so a fresh clone can still run
  # `terraform init` locally (with local state) without that bootstrap
  # step blocking a first read-through of the code.
  #
  # backend "s3" {
  #   bucket         = "cloudops-ai-terraform-state"
  #   key            = "demo-live/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "cloudops-ai-terraform-locks"
  #   encrypt        = true
  # }
}
