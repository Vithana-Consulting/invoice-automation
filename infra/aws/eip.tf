# MySQL's stable public address. App Runner's VPC connector required a NAT
# Gateway (~$32/mo) to give the connector's ENIs internet access at all —
# App Runner routes ALL egress through the VPC once a connector is
# attached, not just the traffic meant for the VPC, and this app also needs
# real internet access (OpenAI, LlamaParse, Google OAuth). Cheaper fix:
# drop the VPC connector, keep MySQL reachable over the public internet on
# a fixed Elastic IP, secured by the generated password instead of network
# isolation.
#
# The EIP itself is billed ~$0.005/hr (~$3.60/mo) whether attached or not
# (AWS's 2024 public IPv4 pricing change) — far cheaper than a NAT Gateway.
#
# A Fargate task gets a fresh ENI every time it starts, so this EIP is
# re-associated to the MySQL task's current ENI by scripts/wake.sh after
# each wake — the IP itself never changes, so DATABASE_URL (below, in
# secrets.tf) is set once and never needs updating.
resource "aws_eip" "mysql" {
  domain = "vpc"
  tags   = { Project = var.project, Purpose = "mysql-stable-ip" }
}
