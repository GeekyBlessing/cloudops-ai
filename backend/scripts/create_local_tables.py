"""Create the DynamoDB tables used by CloudOps AI against DynamoDB Local.

Run this once after `docker-compose up dynamodb-local` and before starting
the API locally with CLOUDOPS_USE_DYNAMODB=true. Idempotent -- safe to
re-run; skips tables that already exist.

This script is for local development against DynamoDB Local ONLY. The real
Terraform module (infra/modules/dynamodb/, not yet built) creates the same
schema in actual AWS -- this script is not a substitute for that module and
should never be pointed at a real AWS account.
"""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

DYNAMODB_LOCAL_ENDPOINT = "http://localhost:8001"
INCIDENTS_TABLE_NAME = "cloudops-ai-incidents"


def create_incidents_table(client: object) -> None:
    """Create the Incidents table with a GSI on (remediation_status,
    created_at) -- the same access pattern the dashboard's incident list
    view needs ("show me AWAITING_APPROVAL incidents, most recent first").
    """
    try:
        client.create_table(  # type: ignore[attr-defined]
            TableName=INCIDENTS_TABLE_NAME,
            KeySchema=[{"AttributeName": "incident_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "incident_id", "AttributeType": "S"},
                {"AttributeName": "remediation_status", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "status-created_at-index",
                    "KeySchema": [
                        {"AttributeName": "remediation_status", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                    "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
                }
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        print(f"Created table {INCIDENTS_TABLE_NAME!r}")
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceInUseException":
            print(f"Table {INCIDENTS_TABLE_NAME!r} already exists, skipping")
        else:
            raise


def main() -> None:
    client = boto3.client(
        "dynamodb",
        endpoint_url=DYNAMODB_LOCAL_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    create_incidents_table(client)


if __name__ == "__main__":
    main()
