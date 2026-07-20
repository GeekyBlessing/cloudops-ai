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
- **`modules/route53`** -- a public Route53 hosted zone for the project's
  custom domain (`cloudops-ai.dev`). Only instantiated in
  `environments/demo-live` -- `dev` and `staging` have no custom domain and
  don't need one.
- **`modules/acm_certificate`** -- requests a DNS-validated ACM certificate
  in `us-east-1` (the only region CloudFront accepts certificates from,
  regardless of `var.aws_region`) and validates it via records created in
  the `route53` module's zone. Also `demo-live`-only.
- **`environments/dev`** -- wires all eight modules together into one
  deployable stack. `environments/demo-live` wires in two more
  (`route53`, `acm_certificate`) for its custom domain -- see "Explicitly
  deferred" below.

### Explicitly deferred (not silently skipped)

- ~~TLS/HTTPS and a custom domain~~ -- **built, for `demo-live` only**.
  `cloudops-ai.dev` now has a Route53 hosted zone (`modules/route53`) and a
  DNS-validated ACM certificate (`modules/acm_certificate`, requested in
  `us-east-1`) attached to `modules/frontend`'s CloudFront distribution via
  its new `aliases` and `acm_certificate_arn` variables. `modules/alb`
  itself is still HTTP-only -- CloudFront terminates TLS, same as before,
  just now with a real certificate for a real domain instead of
  CloudFront's default one. One manual step Terraform cannot do: after
  `apply`, the domain's nameservers have to be set to the four values in
  `terraform output` on the `route53` module, at the registrar -- otherwise
  the hosted zone is just an orphaned AWS resource with nothing pointing at
  it. `dev` and `staging` are unaffected: `modules/frontend`'s `aliases`
  and `acm_certificate_arn` both default to empty, so those environments
  keep using CloudFront's default certificate with no custom domain.
- ~~Single NAT gateway, not one per AZ~~ -- **fixed**. `modules/networking`
  now creates one NAT gateway and one private route table per AZ, so a
  private subnet only ever depends on infrastructure in its own AZ --
  see that module's `aws_nat_gateway` resource comment for the cost
  trade-off (roughly double the fixed monthly NAT cost, ~$32/mo per
  additional gateway).
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

## Three environments

`environments/dev`, `environments/staging`, and `environments/demo-live`
are intentionally near-identical copies of the same `main.tf`/`variables.tf`/
`outputs.tf` shape, not one parameterized module with a `terraform workspace`
or an `environment` variable threaded through it. Each is its own directory
with its own local Terraform state (see "One-time remote state bootstrap"
below for the remote-state alternative), its own `name_prefix` (so the
three never collide on AWS resource names), and its own hardcoded
`CLOUDOPS_REMEDIATION_MODE` value in that file's `module.ecs.environment`
block: `dry_run` for `dev` and `staging`, `live` only for `demo-live`.

Hardcoding the remediation mode per-environment file, instead of exposing
it as a shared variable every environment could accept, is deliberate.
A variable can be overridden at apply time by anyone with a typo or a bad
copy-paste (`-var="remediation_mode=live"` against `dev`, say); a value
that's only ever written down inside `environments/demo-live/main.tf`
cannot leak into another environment's apply without someone editing that
other environment's file directly and it showing up as a real, reviewable
diff. This mirrors the same reasoning behind `core/config.py`'s
application-level default (`dry_run` unless explicitly overridden) and the
HMAC-signed remediation approval flow -- the live-mutation path should
never be the thing that "just happens" if a variable is left unset or
mistyped.

The practical cost of this approach is exactly what it looks like: a
change to, say, `modules/ecs`'s `environment` block or a new module wired
into `main.tf` has to be copied into all three files by hand rather than
changed once. For a project at this stage, reviewable-by-diff safety for
the one environment allowed to mutate real infrastructure was judged more
important than avoiding that duplication.

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
   `modules/ecs`, `modules/ecr`, `modules/eventbridge`,
   `modules/monitoring`, and `modules/frontend` themselves (`dynamodb:*`,
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
   resources instead of just reading the default VPC), and, now that
   `modules/frontend` exists, `s3:CreateBucket`/`s3:DeleteBucket`/
   `s3:PutBucketPolicy`/`s3:GetBucketPolicy`/`s3:DeleteBucketPolicy`/
   `s3:PutBucketPublicAccessBlock`/`s3:GetBucketPublicAccessBlock`/
   `s3:PutBucketOwnershipControls`/`s3:GetBucketOwnershipControls`/
   `s3:GetBucketTagging`/`s3:PutBucketTagging`/`s3:GetBucketLocation`
   (the frontend bucket itself) plus `cloudfront:CreateDistribution`/
   `cloudfront:GetDistribution`/`cloudfront:UpdateDistribution`/
   `cloudfront:DeleteDistribution`/`cloudfront:TagResource`/
   `cloudfront:ListTagsForResource`/`cloudfront:CreateOriginAccessControl`/
   `cloudfront:GetOriginAccessControl`/`cloudfront:UpdateOriginAccessControl`/
   `cloudfront:DeleteOriginAccessControl`/`cloudfront:CreateFunction`/
   `cloudfront:UpdateFunction`/`cloudfront:PublishFunction`/
   `cloudfront:GetFunction`/`cloudfront:DescribeFunction`/
   `cloudfront:DeleteFunction` (the distribution, OAC, and SPA-fallback
   function), and, now that `modules/route53`/`modules/acm_certificate`
   exist (`demo-live`-only), `route53:CreateHostedZone`/
   `route53:GetHostedZone`/`route53:DeleteHostedZone`/
   `route53:ChangeResourceRecordSets`/`route53:ListResourceRecordSets`/
   `route53:GetChange`/`route53:ChangeTagsForResource`/
   `route53:ListTagsForResource` (the hosted zone and its records), plus,
   in `us-east-1` specifically, `acm:RequestCertificate`/
   `acm:DescribeCertificate`/`acm:GetCertificate`/`acm:DeleteCertificate`/
   `acm:AddTagsToCertificate`/`acm:ListTagsForCertificate` (the ACM
   certificate). This is a deliberate, reviewed grant appropriate for a
   role that only a human-triggered, environment-gated workflow can
   assume -- not a rubber stamp.
4. **Two more permissions the deploy job itself calls directly, outside
   `terraform apply`** -- syncing the built dashboard into the frontend
   bucket and busting the CloudFront cache so the new build is actually
   served: `s3:PutObject`/`s3:DeleteObject`/`s3:ListBucket` on the
   frontend bucket (`aws s3 sync`), and `cloudfront:CreateInvalidation`
   on the distribution (`aws cloudfront create-invalidation`). Scope both
   to the specific bucket/distribution ARNs from
   `terraform output frontend_bucket_arn` /
   `terraform output frontend_cloudfront_distribution_arn` rather than
   `*`, once the role's policy is set up by hand -- broad `s3:*`/
   `cloudfront:*` isn't needed for what this workflow actually does after
   the resources exist.

## Frontend hosting

`modules/frontend` puts the built React dashboard in a private S3 bucket
and serves it through a single CloudFront distribution with two origins:
S3 for the dashboard's static files (the default behavior), and the ALB
for every real backend route (`/health`, `/incidents*`, `/remediation*` --
see that module's `api_path_patterns` variable) as ordered behaviors with
caching disabled.

The reason for one distribution instead of two separate things (a static
site plus a directly-called ALB) is TLS: CloudFront terminates HTTPS with
its own default `*.cloudfront.net` certificate, but the ALB only has an
HTTP:80 listener (see "TLS/HTTPS and a custom domain" above). If the
dashboard, served over HTTPS, called the ALB directly over HTTP, the
browser would block every API request as mixed content -- the page would
load but nothing in it would work. Routing `/health`, `/incidents*`, and
`/remediation*` through CloudFront too means the browser only ever talks
to CloudFront over HTTPS; the one remaining plaintext hop is
CloudFront-to-ALB, inside AWS's network, not the public internet.

SPA client-side routing (`/incidents/abc123` on a page reload, which
doesn't correspond to a real S3 object) is handled by a CloudFront
Function attached only to the S3 behavior, not a distribution-wide
`custom_error_response`. `custom_error_response` is keyed by HTTP status
code across the *entire* distribution -- a real 404 from the backend
(an incident that doesn't exist) would also get silently rewritten to
`index.html`, turning a correct API error into a 200 response containing
the SPA shell. Scoping the rewrite to a function on one behavior avoids
that failure mode entirely.

`deploy.yml` builds the dashboard with `VITE_API_BASE_URL=""` (empty
string, not unset -- see `frontend/src/api/client.ts`'s
`?? "http://localhost:8000"` fallback, which only triggers on
null/undefined). An empty base URL makes every API call relative to
whatever origin serves the page, which is exactly right now that the
dashboard and the API live behind the same CloudFront domain -- no need
to bake a specific URL into the build, and no CORS configuration needed
anywhere.

## Structure
