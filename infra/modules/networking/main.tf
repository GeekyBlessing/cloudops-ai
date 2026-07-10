# Custom VPC for the backend's Fargate task -- replaces the account's
# default VPC that modules/ecs previously looked up via data sources.
# Public subnets only: the task still gets a public IP and is reachable
# directly (no ALB yet), so there is nothing for a NAT gateway to serve --
# a NAT gateway only matters for resources in *private* subnets that need
# outbound-only internet access. Private subnets + NAT (and the ALB that
# would have to front the task once it's no longer directly reachable) are
# a deliberate follow-up, not an oversight -- see infra/README.md.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-vpc"
  })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-igw"
  })
}

resource "aws_subnet" "public" {
  count             = length(var.public_subnet_cidrs)
  vpc_id            = aws_vpc.this.id
  cidr_block        = var.public_subnet_cidrs[count.index]
  availability_zone = data.aws_availability_zones.available.names[count.index]

  # The task needs a public IP to be directly reachable (no ALB yet -- see
  # infra/README.md), so subnets that hand one out on launch are what
  # "public" means here, not just "has a route to an IGW".
  map_public_ip_on_launch = true

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-public-${count.index}"
  })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-public-rt"
  })
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}
