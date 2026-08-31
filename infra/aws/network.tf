# Uses the account's default VPC + default public subnets to avoid a NAT
# Gateway (~$32/mo fixed cost). The MySQL Fargate task gets a public IP
# directly from the subnet's Internet Gateway route (needed to pull the
# mysql:8.0 image with no NAT, and now also how App Runner reaches it).
#
# App Runner is NOT in this VPC at all — no VPC connector. An earlier
# version of this config used one so App Runner could reach MySQL
# privately, but App Runner routes ALL egress through a VPC connector once
# one is attached (not just the traffic meant for the VPC), which would
# have required a NAT Gateway anyway for the app's real internet needs
# (OpenAI, LlamaParse, Google OAuth) — defeating the point of avoiding NAT.
# MySQL is reachable over the public internet instead, secured by the
# generated password rather than network isolation. Its public IP changes
# every time the Fargate task restarts (an Elastic IP would fix that, but
# AWS is rejecting EIP association on this account with AuthFailure, likely
# a new-account restriction — see README); scripts/wake.sh updates
# DATABASE_URL in Secrets Manager with the fresh IP after every wake and
# force-redeploys App Runner to pick it up. See the security group below
# for the access tradeoff this implies.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "db" {
  name = "${var.project}-db"
  # NOTE: keep this description text EXACTLY as originally created — AWS
  # does not allow changing an SG's description in place, so any edit here
  # forces a destroy+recreate, which then deadlocks against this SG's own
  # ENIs still being in use (the running MySQL task, EFS mount targets).
  # Change the ingress/egress rules freely; never this string.
  description = "MySQL, reachable only from the app task"
  vpc_id      = data.aws_vpc.default.id

  # SECURITY TRADEOFF: open to the internet, not restricted to a security
  # group or CIDR, because App Runner's default (non-VPC) egress has no
  # static/predictable source IPs to allow-list. Mitigated by: the
  # generated password (see terraform.tfvars, never committed), and this
  # task normally sitting at desired_count=0 (see scripts/sleep.sh) — the
  # exposure window is only while actually in use, not continuous.
  ingress {
    description = "MySQL - open to the internet, see SECURITY TRADEOFF note above"
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Project = var.project }
}

resource "aws_security_group" "efs" {
  name = "${var.project}-efs"
  # NOTE: keep this description text EXACTLY as originally created — see the
  # matching note on aws_security_group.db above. Changing it here is what
  # caused the stuck destroy (this SG's mount-target ENIs must persist
  # unchanged, so a forced replacement can never actually complete).
  description = "NFS from app + db tasks"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "NFS from db task"
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.db.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Project = var.project }
}
