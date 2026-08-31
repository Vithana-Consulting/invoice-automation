# Single combined image for App Runner (frontend+backend in one container —
# App Runner runs exactly one container per service, see
# infra/aws/apprunner/Dockerfile). Replaces the separate backend/frontend/
# caddy repos from the earlier Fargate-based design.
resource "aws_ecr_repository" "app" {
  name                 = "${var.project}-app"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # so `terraform destroy` doesn't get stuck on "repository not empty"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 5 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}
