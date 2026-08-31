# Monthly cost alert for this project specifically (filtered by the
# "Project = vithana" tag most resources here carry — not the whole AWS
# account's spend). Three notification checkpoints: $5, $10, and 100% of
# the $15 budget limit as a final "you're over budget" signal. AWS Budgets
# sends the email itself — no Lambda/Gmail API/custom code needed.
#
# Cost estimate for this whole setup is ~$5-15/mo with light wake/sleep
# usage (see README.md / DEPLOYMENT_LOG.md) — these thresholds are meant to
# catch the "forgot to run sleep.sh for a few days" scenario well before it
# gets expensive, not to be a precise real-time cost tracker (AWS Budgets
# data typically lags actual spend by ~8-24 hours).

resource "aws_budgets_budget" "monthly" {
  name         = "${var.project}-monthly"
  budget_type  = "COST"
  limit_amount = "15"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name = "TagKeyValue"
    # format(), not "...$${var.project}" — Terraform's $${ is a literal-${
    # escape sequence, which would leave the LITERAL TEXT "${var.project}"
    # in the filter instead of substituting the actual value.
    values = [format("user:Project$%s", var.project)]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 5
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["vithanaconsulting@gmail.com"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 10
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["vithanaconsulting@gmail.com"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["vithanaconsulting@gmail.com"]
  }
}
