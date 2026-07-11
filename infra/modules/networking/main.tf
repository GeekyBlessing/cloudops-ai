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

# One NAT gateway per AZ, not a single shared one -- this used to be a
# single NAT gateway in aws_subnet.public[0], documented as a deliberate
# cost trade-off (see infra/README.md's former "Single NAT gateway"
# deferred bullet). That trade-off meant an outage in the NAT gateway's
# own AZ took out outbound internet access for the private-subnet task in
# the *other* AZ too, even though that AZ was otherwise healthy -- a real
# gap once anything besides a single-task portfolio deployment is at
# stake. Fixed here at roughly double the fixed monthly NAT cost (~$32/mo
# per additional gateway, plus per-GB data processing) by giving every AZ
# its own NAT gateway and its own private route table, so a private
# subnet only ever depends on infrastructure in its own AZ.
resource "aws_eip" "nat" {
  count  = length(var.private_subnet_cidrs)
  domain = "vpc"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-nat-eip-${count.index}"
  })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_nat_gateway" "this" {
  count         = length(var.private_subnet_cidrs)
  allocation_id = aws_eip.nat[count.index].id
  # Indexed the same as aws_subnet.private -- this NAT gateway lives in
  # the public subnet in the *same* AZ as the private subnet it serves,
  # which is what makes each private subnet independent of every other
  # AZ's NAT gateway. Assumes var.public_subnet_cidrs and
  # var.private_subnet_cidrs are the same length, one entry per AZ used
  # -- already an implicit assumption elsewhere in this file (the public
  # and private route table associations both index by count.index too).
  subnet_id = aws_subnet.public[count.index].id

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-nat-${count.index}"
  })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route_table" "private" {
  count  = length(var.private_subnet_cidrs)
  vpc_id = aws_vpc.this.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this[count.index].id
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-private-rt-${count.index}"
  })
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}
