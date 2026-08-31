# Uses the account's default VPC + default public subnets to avoid a NAT
# Gateway (~$32/mo fixed cost we don't need here). The MySQL Fargate task
# gets a public IP directly from the subnet's Internet Gateway route
# (needed to pull the mysql:8.0 image with no NAT). App Runner itself is
# NOT in this VPC — it's a public, internet-facing PaaS by design — it only
# touches the VPC via the connector below, to privately reach MySQL.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ENIs App Runner creates in our VPC to reach MySQL privately (its own
# public endpoint traffic never touches this SG).
resource "aws_security_group" "apprunner_connector" {
  name        = "${var.project}-apprunner-connector"
  description = "Egress-only SG for the App Runner VPC connector ENIs"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Project = var.project }
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

  ingress {
    description     = "MySQL from App Runner VPC connector"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.apprunner_connector.id]
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
