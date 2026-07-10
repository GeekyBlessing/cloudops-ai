# CloudOps AI -- Infrastructure (Terraform)

## Scope of this chunk

`/docs/PROJECT_STRUCTURE.md` lays out eight planned modules (networking,
ecs, lambda, dynamodb, eventbridge, iam, monitoring, frontend) plus three
environments. Building all of that in one pass would mean shipping eight
under-reviewed modules instead of a smaller number that are actually
correct, so this was built incrementally across several chunks:

- **`modules/networking`** -- a VPC with public subnets across two AZs, an
  Internet Gateway, and route tables. Replaces the account's default VPC
  that `modules/ecs` used to look up via data sources. No private subnets
  or NAT gateway yet -- the task still needs a public IP to be directly
  reachable since there's no ALB (see "Explicitly deferred" below).
- **`modules/dynamodb`** -- the Incidents table, schema-matched to
  `backend/scripts/create_local_tables.py`.
- **`modules/iam`** -- `MonitoringReadOnlyRole` and `RemediationExecutorRole`,
  scoped to the exact boto3 calls `Boto3AWSGateway` and
  `Boto3MutatingAWSGateway` make (not broad service access), plus an ECS
  task execution role and SQS consume permissions for the poller.
- **`modules/ecs`** -- a Fargate cluster/task/service running the backend
  container in `modules/networking`'s public subnets, with a public IP and
  no ALB.
- **`modules/ecr`** -- a single ECR repository for the backend image
  (immutable tags, scan-on-push, lifecycle policy for untagged images).
  Added alongside `.github/workflows/deploy.yml`, once the Docker chunk
  made "build and push a real image" possible.
- **`modules/eventbridge`** -- the CloudWatch Alarm -> EventBridge -> SQS
  pipeline that feeds incidents into the backend's SQS poller
  (`backend/src/cloudops_ai/services/sqs_incident_poller.py`), as an
  alternative entry point to the dashboard's manual "New incident" form.
- **`modules/monitoring`** -- an SNS alerts topic plus CloudWatch alarms on
  the backend's own health: ECS CPU/memory, the incident-triggers DLQ
  depth (previously unwatched -- see the old "Explicitly deferred" entry
  this replaces), and the age of the oldest unprocessed message in the
  main queue as a proxy for "the SQS poller has stopped consuming." Also a
  CloudWatch dashboard summarizing all of it.
- **`environments/dev`** -- wires all seven modules together into one
  deployable stack.

### Explicitly deferred (not silently skipped)

- **Private subnets, NAT gateway, and an ALB.** `modules/networking` only
  builds public subnets so far -- the task's security group is still
  exposed directly to `0.0.0.0/0` on the API port (overridable via
  `modules/ecs`'s `allowed_ingress_cidr_blocks` variable, but open by
  default). Moving the task into private subnets requires an ALB in front
  of it first (otherwise nothing could reach it at all), plus a NAT
  gateway or VPC endpoints for its outbound AWS API calls. That's a larger
  chunk than "add a VPC" on its own, so it's deferred rather than half-done.
- **ALB.** No load balancer, no TLS, no stable DNS name -- you get the
  task's public IP after `terraform apply`, which changes every time the
  service redeploys. Fine for kicking the tires, not for anything you'd
  bookmark.
- **Frontend S3+CloudFront module** -- not started. The frontend Docker
  image (`frontend/Dockerfile`, nginx-based) exists but has no ECR
  repository or hosting target in Terraform yet -- `deploy.yml` only
  builds/pushes the backend image. Add a second `aws_ecr_repository` in
  `modules/ecr` and a real hosting target when this gets built, rather
  than provisioning storage for an image nothing deploys.
- **Alarm-to-incident-pipeline feedback loop.** `modules/monitoring`'s
  alarms notify an SNS topic (optionally by email), but they are not
  wired into `modules/eventbridge`'s CloudWatch-Alarm-state-change rule --
  a DLQ or ECS-health alarm firing does not itself create an incident in
  this system. Doing that on purpose (rather than as an accident of two
  modules technically being able to reach each other) is a real follow-up:
  it would mean this project's own infrastructure problems flow through
  the same triage pipeline as the AWS resources it monitors on your
  behalf, which is a bigger design decision than this chunk's scope.
- **staging/ and demo-live/ environments** -- only `environments/dev`
  exists. `demo-live` in particular (the only environment meant to ever run
  `CLOUDOPS_REMEDIATION_MODE=live`) is a real follow-up, not a rename of
  `dev`.

## A note on verification

Every previous chunk in this project was verified with a real test run
(`pytest` for Python, `tsc`/`vite build` for the frontend) before being
handed off. I could not do the equivalent here: the sandbox this was built
in blocks network access to `releases.hashicorp.com` and GitHub release
downloads, so the Terraform CLI itself could not be installed, and
`terraform validate`/`plan` need a real provider plugin download regardless
of sandboxing. I read through every file carefully, parsed each changed
file with a standalone HCL parser to catch syntax errors, and
cross-checked every variable reference and module output against its
consumer by hand -- but that is not a substitute for actually running:

```bash
cd environments/dev
terraform fmt -check -recursive ..
terraform init
terraform validate
terraform plan -var="image_tag=<any-placeholder-string-is-fine-for-a-plan>"
```

Please run those four commands and paste back anything other than a clean
result -- this is the one chunk in the project where "it compiled in my
sandbox" isn't something I can honestly claim.

`terraform plan` should show, across the two chunks that added
`modules/networking` and `modules/monitoring`: a VPC, an Internet Gateway,
two subnets, a route table, and two route table associations from
`modules/networking`; an SNS topic (plus an email subscription if
`var.alert_email` is set), four CloudWatch metric alarms, and a CloudWatch
dashboard from `modules/monitoring`; two new outputs on
`modules/eventbridge` (`queue_name`, `dlq_name` -- outputs only, no new
resources); and `modules/ecs`'s existing security group/cluster/task/service
depending on the new VPC's ID and subnet IDs instead of the default VPC's.

## One-time remote state bootstrap (optional)

`environments/dev/versions.tf` has an S3 backend block commented out.
Local state (the default if you leave it commented) works fine for trying
this out solo. If you want remote state (recommended before anyone else
touches this, or before wiring up CI), create the backing resources first
-- Terraform can't create the state bucket it also wants to store its
state in:

```bash
aws s3api create-bucket --bucket cloudops-ai-terraform-state --region us-east-1
aws s3api put-bucket-versioning \
  --bucket cloudops-ai-terraform-state \
  --versioning-configuration Status=Enabled

aws dynamodb create-table \
  --table-name cloudops-ai-terraform-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

Then uncomment the `backend "s3" { ... }` block in `versions.tf` and run
`terraform init -migrate-state`.

## Applying this manually

```bash
cd environments/dev
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars -- image_tag needs to point at a commit SHA that
# has actually been built and pushed (see "CI/CD: deploy.yml" below for
# the automated path, or build/push by hand with `docker build`/`docker
# push` against the ecr module's repository_url output for a one-off).
# Also set alert_email if you want modules/monitoring's alarms to
# actually notify someone -- see modules/monitoring's alert_email
# variable description. Left unset, the SNS topic and every alarm are
# still created, just silent until something subscribes to
# monitoring_sns_topic_arn.
terraform init
terraform plan
terraform apply
```

If you already have this stack applied from before the VPC-hardening
chunk, the plan will show your existing ECS resources being replaced (new
security group, new task definition revision) because they're moving from
the default VPC into `modules/networking`'s VPC -- this is a real (brief)
service interruption on `terraform apply`, not just a diff artifact.
Nothing stateful (the DynamoDB table, the ECR repository) is affected.
`modules/monitoring`'s resources are all new adds, not replacements --
applying them causes no interruption.

## CI/CD: deploy.yml

`.github/workflows/deploy.yml` automates the manual steps above: it builds
the backend image, pushes it to ECR tagged with the triggering commit's
git SHA, and runs `terraform apply` to roll it out. It's a
**`workflow_dispatch`-only** trigger -- not automatic on push to `main` --
deliberately mirroring this project's human-gated-by-default posture
elsewhere (`CLOUDOPS_REMEDIATION_MODE` defaults to `dry_run`; remediation
actions require an HMAC-signed approval token). Deploying to a real AWS
account is exactly the kind of action that shouldn't happen silently on
every merge.

To actually run it, three pieces of one-time AWS/GitHub-side setup are
needed (none of this is automatable from within the workflow file itself
-- same bootstrap-problem shape as the remote state backend above):

1. **A GitHub Environment** named `aws-dev` (Settings -> Environments ->
   New environment), with required reviewers configured if you want an
   actual human-approval gate enforced by GitHub before the job runs, not
   just a manual trigger.
2. **An OIDC-trusted IAM role for deploys**, separate from the
   `AWS_GITHUB_ACTIONS_ROLE_ARN` role `terraform-plan.yml` already uses.
   The plan role only ever needs read access and runs on every PR from any
   branch; the deploy role needs broad write access (dynamodb, iam, ecs,
   ecr, ec2, events, sqs, logs -- everything this Terraform config
   manages) and only runs on a manual, reviewed dispatch. Reusing one role
   for both would mean a compromised or misconfigured PR-triggered
   workflow could assume production-mutating permissions. Store its ARN in
   the `AWS_GITHUB_ACTIONS_DEPLOY_ROLE_ARN` repository secret.
3. The deploy role's policy needs, at minimum: `ecr:GetAuthorizationToken`,
   `ecr:BatchCheckLayerAvailability`, `ecr:PutImage`,
   `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`,
   `ecr:CompleteLayerUpload` (to push images), plus everything
   `terraform apply` needs to create/update the resources in
   `modules/networking`, `modules/dynamodb`, `modules/iam`, `modules/ecs`,
   `modules/ecr`, `modules/eventbridge`, and `modules/monitoring`
   themselves (`dynamodb:*`, `iam:CreateRole`/`PutRolePolicy`/etc.,
   `ecs:*`, `ecr:CreateRepository`/`PutLifecyclePolicy`/etc., `events:*`,
   `sqs:*`, `logs:*`, `cloudwatch:PutMetricAlarm`/`DeleteAlarms`/
   `PutDashboard`/`DeleteDashboards`/`Describe*`, `sns:CreateTopic`/
   `Subscribe`/`SetTopicAttributes`/`DeleteTopic`, and full
   `ec2:*Vpc*`/`ec2:*Subnet*`/`ec2:*RouteTable*`/`ec2:*InternetGateway*`/
   `ec2:CreateTags`/`ec2:Describe*` now that `modules/networking` creates
   and owns VPC resources instead of just reading the default VPC). This
   is a deliberate, reviewed grant appropriate for a role that only a
   human-triggered, environment-gated workflow can assume -- not a rubber
   stamp.

## Structure
