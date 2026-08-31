# One JSON secret instead of one-per-value: Secrets Manager bills per secret
# ($0.40/mo each), so bundling ~8 values into one secret keeps this at
# $0.40/mo total instead of ~$3/mo.

resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.project}/app"
  recovery_window_in_days = 0 # internal tool, no need for the 30-day recovery hold

  tags = { Project = var.project }
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    MYSQL_ROOT_PASSWORD = var.mysql_root_password
    MYSQL_PASSWORD      = var.mysql_password
    # Placeholder — MySQL's Fargate task gets a fresh public IP every time it
    # wakes (an Elastic IP would fix this, but AWS is rejecting EIP
    # association on this account with AuthFailure, likely a new-account
    # restriction — see README). scripts/wake.sh overwrites this field with
    # the task's real current IP via `aws secretsmanager put-secret-value`
    # after every wake, then force-redeploys App Runner so it picks up the
    # new value (secrets are only read at container start).
    DATABASE_URL               = "mysql+pymysql://accounting:${var.mysql_password}@PLACEHOLDER-see-wake.sh:3306/accounting_automation"
    JWT_SECRET_KEY             = var.jwt_secret_key
    ADMIN_API_KEY              = var.admin_api_key
    INTEGRATION_ENCRYPTION_KEY = var.integration_encryption_key
    LLM_API_KEY                = var.llm_api_key
    LLAMAPARSE_API_KEY         = var.llamaparse_api_key
    GOOGLE_CLIENT_ID           = var.google_client_id
    GOOGLE_CLIENT_SECRET       = var.google_client_secret
  })

  # wake.sh owns DATABASE_URL's real value from here on (see above) — without
  # this, the next `terraform apply` would stomp wake.sh's live update back
  # to the placeholder. Tradeoff: changing any OTHER field in this secret
  # (rotating JWT_SECRET_KEY, etc.) via tfvars + apply won't take effect
  # either while this is in place; update those via the AWS CLI/Console
  # directly instead, or temporarily remove this block to push a tfvars
  # change through.
  lifecycle {
    ignore_changes = [secret_string]
  }
}
