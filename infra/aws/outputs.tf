output "ecr_backend_repo" {
  value = aws_ecr_repository.backend.repository_url
}

output "ecr_frontend_repo" {
  value = aws_ecr_repository.frontend.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "app_service_name" {
  value = aws_ecs_service.app.name
}

output "db_service_name" {
  value = aws_ecs_service.db.name
}

output "secret_arn" {
  value = aws_secretsmanager_secret.app.arn
}
