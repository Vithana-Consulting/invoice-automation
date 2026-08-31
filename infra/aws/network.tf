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
  description = "Egress-only SG for the App Runner VPC connector's ENIs"
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
  name        = "${var.project}-db"
  description = "MySQL, reachable only from the App Runner VPC connector"
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
  name        = "${var.project}-efs"
  description = "NFS from the db task (mysql data only now — attachments moved to S3)"
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
