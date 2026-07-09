# Incidents table. Schema mirrors backend/scripts/create_local_tables.py
# exactly -- that script bootstraps the same shape against DynamoDB Local
# for development; this resource is what creates it for real. See
# backend/src/cloudops_ai/repositories/dynamodb_incident_repository.py for
# the item shape this table actually stores (top-level queryable attributes
# plus one JSON-blob "document" attribute).
resource "aws_dynamodb_table" "incidents" {
  name         = var.table_name
  billing_mode = var.billing_mode
  hash_key     = "incident_id"

  attribute {
    name = "incident_id"
    type = "S"
  }

  attribute {
    name = "remediation_status"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  # Supports the dashboard's incident list query pattern: "show me
  # AWAITING_APPROVAL incidents, most recent first" -- without this GSI
  # that query would require a full table scan plus client-side filtering.
  global_secondary_index {
    name            = "status-created_at-index"
    hash_key        = "remediation_status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = merge(var.tags, {
    Name = var.table_name
  })
}
