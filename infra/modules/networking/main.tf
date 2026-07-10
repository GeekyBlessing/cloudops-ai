# VPC for the backend: public subnets for the ALB, private subnets (with a
# NAT gateway for outbound-only internet access) for the Fargate task
# itself. modules/ecs used to place the task directly in a public subnet
# with a public IP and no ALB -- that's what this module upgrades away
# from. See infra/README.md for the ALB module this pairs with.

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

  # Only the ALB (modules/alb) lives here now -- the backend task itself
  # moved to the private subnets below. A subnet that hands out a public
  # IP on launch is still what "public" means here.
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

resource "aws_subnet" "private" {
  count             = length(var.private_subnet_cidrs)
  vpc_id            = aws_vpc.this.id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = data.aws_availability_zones.available.names[count.index]

  # Explicitly false (also the default) -- this is the entire point of
  # the private subnet. The task reaches the internet outbound-only via
  # the NAT gateway below, and is only reachable inbound via the ALB in
  # the public subnets (modules/alb), never directly.
  map_public_ip_on_launch = false

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-private-${count.index}"
  })
}

# A single NAT gateway in one AZ, not one per AZ -- a real cost trade-off,
# not an oversight: each NAT gateway costs ~$32/month plus per-GB data
# processing, so two would roughly double that fixed cost. The trade-off
# is that if this NAT gateway's AZ has an outage, the task in the *other*
# AZ loses outbound internet access too (it still has a route to this NAT
# gateway, just not a local one). For a single-task portfolio deployment
# (environments/dev's desired_count defaults to 1) that asymmetric
# resilience gap matters far less than it would in production -- tracked
# as a real follow-up in infra/README.md, not silently accepted.
resource "aws_eip" "nat" {
  domain = "vpc"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-nat-eip"
  })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-nat"
  })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this.id
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-private-rt"
  })
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
