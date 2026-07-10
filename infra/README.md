# CloudOps AI -- Infrastructure (Terraform)

## Scope of this chunk

`/docs/PROJECT_STRUCTURE.md` lays out eight planned modules (networking,
ecs, lambda, dynamodb, eventbridge, iam, monitoring, frontend) plus three
environments. Building all of that in one pass would mean shipping eight
under-reviewed modules instead of a smaller number that are actually
correct, so this was built incrementally across several chunks:

- **`modules/networking`** -- a VPC with public subnets (now for
  `modules/alb`) and private subnets (now for `modules/ecs`) across two
  AZs, an Internet Gateway, a single NAT gateway, and route tables.
  Replaces the account's default VPC that `modules/ecs` used to look up
  via data sources.
- **`modules/dynamodb`** -- the Incidents table, schema-matched to
  `backend/scripts/create_local_tables.py`.
- **`modules/iam`** -- `MonitoringReadOnlyRole` and `RemediationExecutorRole`,
  scoped to the exact boto3 calls `Boto3AWSGateway` and
  `Boto3MutatingAWSGateway` make (not broad service access), plus an ECS
  task execution role and SQS consume permissions for the poller.
- **`modules/ecs`** -- a Fargate cluster/task/service running the backend
  container in `modules/networking`'s private subnets, with no public IP.
  Reachable only through `modules/alb`.
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
- **`modules/alb`** -- an Application Load Balancer, target group (health
  checked against the backend's `/health` endpoint), and HTTP:80 listener
  in `modules/networking`'s public subnets. This is what makes moving
  `modules/ecs`'s task into private subnets possible at all -- it's the
  only thing left with direct internet exposure, and it gives the backend
  a stable DNS name (the `alb_dns_name` output) that no longer changes on
  every redeploy the way the task's old public IP did.
- **`environments/dev`** -- wires all eight modules together into one
  deployable stack.

### Explicitly deferred (not silently skipped)

- **TLS/HTTPS and a custom domain.** `modules/alb`'s listener is HTTP-only
  on port 80 -- there is no ACM certificate and no Route53 hosted zone,
  because there's no domain name for this project to get one for. The ALB
  gives a stable DNS name, not encryption in transit. Adding TLS later
  means buying/registering a domain, creating a Route53 zone, requesting
  an ACM cert with DNS validation, and adding an HTTPS listener (with the
  HTTP one either removed or redirecting to it) -- a real chunk of its
  own, not a config flag.
- **Single NAT gateway, not one per AZ.** `modules/networking` creates one
  NAT gateway in one AZ to halve the fixed monthly cost -- see that
  module's `aws_nat_gateway` resource comment for the full trade-off. If
  that AZ has an outage, the private-subnet task in the *other* AZ loses
  outbound internet access too, even though it's otherwise healthy. Low
  stakes for a single-task portfolio deployment, a real gap for anything
  meant to survive an AZ failure.
- **Frontend S3+CloudFront module** -- not started. The frontend Docker
  image (`frontend/Dockerfile`, nginx-based) exists but has no ECR
  repository or hosting target in Terraform yet -- `deploy.yml` only
  builds/pushes the backend image. Add a second `aws_ecr_repository` in
  `modules/ecr` and a real hosting target when this gets built, rather
  than provisioning storage for an image nothing deploys.
- ~~Alarm-to-incident-pipeline feedback loop~~ -- **correction, not a
  build**: this bullet previously claimed `modules/monitoring`'s alarms
  "are not wired into" `modules/eventbridge`'s CloudWatch-Alarm-state-change
  rule. That was wrong. That rule has no alarm-ARN filter -- it matches
  *any* CloudWatch alarm entering ALARM state in the account, which means
  `modules/monitoring`'s alarms were already reaching the incident-triggers
  queue the moment that module was applied, several chunks ago. The actual
  gap was on the backend, not here: `coordinator.py`'s `classify_node` was
  asking an LLM to force one of those alarms into an `IncidentType` meant
  for customer AWS resources (a plausible misfire: the ECS CPU alarm
  guessed as `EC2_HIGH_CPU`, routing to `monitoring_agent.py`, which would
  call `get_metric_data` with the alarm's own ARN as an `InstanceId`
  dimension -- not a crash, but a wrong, misleading investigation result).
  Fixed with a deterministic `IncidentType.PLATFORM_HEALTH_ALARM`
  classification in `coordinator.py`, checked before the LLM ever runs --
  see that file's docstring for the full explanation. No Terraform changed
  for this fix, which is exactly the point: the infra was already correct,
  the backend's trust boundary around the LLM wasn't.
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

For a fresh `terraform apply` (nothing applied yet), `terraform plan`
should show 34 resources across `modules/networking` (VPC, IGW, 2 public +
2 private subnets, 1 EIP, 1 NAT gateway, 2 route tables, 4 route table
associations), `modules/alb` (security group, load balancer, target
group, listener), `modules/monitoring` (SNS topic, 4 alarms, dashboard),
plus the pre-existing `modules/dynamodb`/`modules/ecr`/`modules/ecs`/
`modules/eventbridge`/`modules/iam` resources.

If you already had the pre-ALB stack applied, expect `modules/ecs`'s
security group, task definition, and service to be **replaced** (not just
changed) -- the task is moving from a public subnet with a public IP to a
private one behind a load balancer, which touches the ECS service's
`network_configuration` and `load_balancer` block in ways Terraform can't
do in place. That's a real, brief interruption on `apply`. Nothing
stateful is affected.

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

After applying, point the dashboard at the backend's new stable address
instead of the old floating task public IP:

```bash
# frontend/.env.local
echo "VITE_API_BASE_URL=http://$(terraform output -raw alb_dns_name)" > ../../frontend/.env.local
```

See the note on `terraform plan` above ("A note on verification") for what
to expect if you're applying this on top of an existing pre-ALB stack --
`modules/ecs`'s resources get replaced, not just changed, and that's a
real (brief) interruption. Nothing stateful (the DynamoDB table, the ECR
repository) is affected. `modules/monitoring` and `modules/alb`'s own
resources are all new adds, not replacements -- applying them on their own
causes no interruption.

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
   `modules/networking`, `modules/alb`, `modules/dynamodb`, `modules/iam`,
   `modules/ecs`, `modules/ecr`, `modules/eventbridge`, and
   `modules/monitoring` themselves (`dynamodb:*`,
   `iam:CreateRole`/`PutRolePolicy`/etc., `ecs:*`,
   `ecr:CreateRepository`/`PutLifecyclePolicy`/etc., `events:*`, `sqs:*`,
   `logs:*`, `cloudwatch:PutMetricAlarm`/`DeleteAlarms`/`PutDashboard`/
   `DeleteDashboards`/`Describe*`, `sns:CreateTopic`/`Subscribe`/
   `SetTopicAttributes`/`DeleteTopic`, `elasticloadbalancing:*` (the ALB,
   target group, and listener), and full
   `ec2:*Vpc*`/`ec2:*Subnet*`/`ec2:*RouteTable*`/`ec2:*InternetGateway*`/
   `ec2:*NatGateway*`/`ec2:AllocateAddress`/`ec2:ReleaseAddress`/
   `ec2:DescribeAddresses`/`ec2:CreateTags`/`ec2:Describe*` now that
   `modules/networking` creates and owns VPC, subnet, and NAT gateway
   resources instead of just reading the default VPC). This is a
   deliberate, reviewed grant appropriate for a role that only a
   human-triggered, environment-gated workflow can assume -- not a rubber
   stamp.

## Structure
