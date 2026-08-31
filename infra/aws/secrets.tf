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
    MYSQL_ROOT_PASSWORD        = var.mysql_root_password
    MYSQL_PASSWORD             = var.mysql_password
    DATABASE_URL               = "mysql+pymysql://accounting:${var.mysql_password}@${aws_service_discovery_service.db.name}.${var.project}.internal:3306/accounting_automation"
    JWT_SECRET_KEY             = var.jwt_secret_key
    ADMIN_API_KEY              = var.admin_api_key
    INTEGRATION_ENCRYPTION_KEY = var.integration_encryption_key
    LLM_API_KEY                = var.llm_api_key
    LLAMAPARSE_API_KEY         = var.llamaparse_api_key
    GOOGLE_CLIENT_ID           = var.google_client_id
    GOOGLE_CLIENT_SECRET       = var.google_client_secret
  })
}
