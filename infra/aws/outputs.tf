output "ecr_app_repo" {
  value = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "db_service_name" {
  value = aws_ecs_service.db.name
}

output "apprunner_service_arn" {
  value = aws_apprunner_service.app.arn
}

output "apprunner_url" {
  description = "Stable HTTPS URL — this does not change across wakes, unlike the earlier sslip.io setup."
  value       = "https://${aws_apprunner_service.app.service_url}"
}

output "s3_attachments_bucket" {
  value = aws_s3_bucket.attachments.bucket
}

output "secret_arn" {
  value = aws_secretsmanager_secret.app.arn
}

output "deployer_iam_user" {
  description = "Run `aws iam create-access-key --user-name <this>` to get real credentials for this user — the access key itself is NOT a Terraform resource (see iam-user.tf)."
  value       = aws_iam_user.deployer.name
}
