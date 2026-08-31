# Frontend+backend combined service. Replaces the ECS "app" task + Caddy
# sidecar — App Runner terminates TLS itself and gives a stable
# https://<id>.<region>.awsapprunner.com URL, so there's no on-demand-TLS/
# sslip.io machinery needed here at all.

resource "aws_apprunner_vpc_connector" "this" {
  vpc_connector_name = "${var.project}-connector"
  subnets            = data.aws_subnets.default.ids
  security_groups    = [aws_security_group.apprunner_connector.id]
}

# App Runner's own auto-scaling config. MinSize=1 — unlike the Fargate
# desired_count=0 pattern, App Runner has no automatic scale-to-zero; the
# nearest equivalent is a MANUAL pause/resume API call (see scripts/wake.sh
# and scripts/sleep.sh), which stops/starts billing similarly but isn't
# traffic-triggered the way ECS's desired_count toggle isn't either.
resource "aws_apprunner_auto_scaling_configuration_version" "this" {
  auto_scaling_configuration_name = "${var.project}-app"
  min_size                        = 1
  max_size                        = 2
  max_concurrency                 = 50
}

resource "aws_apprunner_service" "app" {
  service_name = "${var.project}-app"

  source_configuration {
    auto_deployments_enabled = false # deploy explicitly via force-update, matching the ECS force-new-deployment pattern — avoids surprise redeploys on an unrelated `docker push`

    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_access.arn
    }

    image_repository {
      image_repository_type = "ECR"
      image_identifier      = var.app_image != "" ? var.app_image : "${aws_ecr_repository.app.repository_url}:latest"

      image_configuration {
        port = "3000"

        runtime_environment_variables = {
          APP_NAME        = "vithana-accounting-platform"
          DEBUG           = "false"
          PARSER_MODE     = "llm"
          LLM_PROVIDER    = "openai"
          LLM_MODEL       = "gpt-4o"
          ATTACHMENT_DIR  = "data/attachments" # only used as a /tmp staging subdir now; real storage is S3 (STORAGE_BACKEND below)
          STORAGE_BACKEND = "s3"
          S3_BUCKET_NAME  = aws_s3_bucket.attachments.bucket
          S3_REGION       = var.aws_region
        }

        runtime_environment_secrets = {
          for k in [
            "DATABASE_URL", "JWT_SECRET_KEY", "ADMIN_API_KEY",
            "INTEGRATION_ENCRYPTION_KEY", "LLM_API_KEY", "LLAMAPARSE_API_KEY",
            "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
          ] : k => "${aws_secretsmanager_secret.app.arn}:${k}::"
        }
      }
    }
  }

  instance_configuration {
    cpu               = var.apprunner_cpu
    memory            = var.apprunner_memory
    instance_role_arn = aws_iam_role.apprunner_instance.arn
  }

  network_configuration {
    egress_configuration {
      egress_type       = "VPC"
      vpc_connector_arn = aws_apprunner_vpc_connector.this.arn
    }
  }

  auto_scaling_configuration_arn = aws_apprunner_auto_scaling_configuration_version.this.arn

  health_check_configuration {
    protocol = "TCP" # HTTP health check would need a path that's always 200 regardless of auth state; TCP is simpler and matches how the Fargate setup had no ALB-style health check either
  }

  tags = { Project = var.project }
}
