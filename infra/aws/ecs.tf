resource "aws_ecs_cluster" "this" {
  name = "${var.project}-cluster"
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name = aws_ecs_cluster.this.name

  capacity_providers = ["FARGATE_SPOT", "FARGATE"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT" # ~70% cheaper than on-demand Fargate; fine for an internal tool that tolerates interruption
    weight            = 100
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.project}/app"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "db" {
  name              = "/ecs/${var.project}/db"
  retention_in_days = var.log_retention_days
}

# --- app task: frontend + backend in one task (same network namespace, ---
# --- so the frontend proxies to the backend over localhost — no ALB, ---
# --- no dependency on the task's public IP for internal container calls) ---
resource "aws_ecs_task_definition" "app" {
  family                   = "${var.project}-app"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 4096 # bumped from 3072 to make room for the Caddy sidecar
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn             = aws_iam_role.task.arn

  volume {
    name = "attachments"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.data.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.attachments.id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = "backend"
      image     = var.backend_image != "" ? var.backend_image : "${aws_ecr_repository.backend.repository_url}:latest"
      essential = true
      portMappings = [{ containerPort = 8000, protocol = "tcp" }]

      mountPoints = [{
        sourceVolume  = "attachments"
        containerPath = "/app/data/attachments"
      }]

      environment = [
        { name = "APP_NAME", value = "vithana-accounting-platform" },
        { name = "DEBUG", value = "false" },
        { name = "PARSER_MODE", value = "llm" },
        { name = "LLM_PROVIDER", value = "openai" },
        { name = "LLM_MODEL", value = "gpt-4o" },
        { name = "ATTACHMENT_DIR", value = "data/attachments" },
      ]

      secrets = [
        for k in [
          "DATABASE_URL", "JWT_SECRET_KEY", "ADMIN_API_KEY",
          "INTEGRATION_ENCRYPTION_KEY", "LLM_API_KEY", "LLAMAPARSE_API_KEY",
          "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
        ] : { name = k, valueFrom = "${aws_secretsmanager_secret.app.arn}:${k}::" }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.app.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "backend"
        }
      }
    },
    {
      name      = "frontend"
      image     = var.frontend_image != "" ? var.frontend_image : "${aws_ecr_repository.frontend.repository_url}:latest"
      essential = true
      portMappings = [{ containerPort = 3000, protocol = "tcp" }]

      # NOTE: Next.js bakes both of these into the build at `npm run build`
      # time (see scripts/build-and-push.sh) — setting them here as
      # container runtime env vars has NO effect on the already-compiled
      # image. Left unset here deliberately so nobody mistakes this for the
      # place to change them. In particular, do NOT set NEXT_PUBLIC_API_URL
      # here expecting it to override the client bundle — it can't; it's
      # frozen into the JS at build time and runs in the end user's browser.

      dependsOn = [{ containerName = "backend", condition = "START" }]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.app.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "frontend"
        }
      }
    },
    {
      name      = "caddy"
      image     = var.caddy_image != "" ? var.caddy_image : "${aws_ecr_repository.caddy.repository_url}:latest"
      essential = true
      portMappings = [
        { containerPort = 443, protocol = "tcp" },
        { containerPort = 80, protocol = "tcp" },
      ]

      dependsOn = [{ containerName = "frontend", condition = "START" }]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.app.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "caddy"
        }
      }
    }
  ])
}

# --- db task: MySQL 8.0, official image, data on EFS ---
resource "aws_ecs_task_definition" "db" {
  family                   = "${var.project}-db"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn             = aws_iam_role.task.arn

  volume {
    name = "mysql-data"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.data.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.mysql_data.id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = "mysql"
      image     = "mysql:8.0"
      essential = true
      portMappings = [{ containerPort = 3306, protocol = "tcp" }]

      mountPoints = [{
        sourceVolume  = "mysql-data"
        containerPath = "/var/lib/mysql"
      }]

      environment = [
        { name = "MYSQL_DATABASE", value = "accounting_automation" },
        { name = "MYSQL_USER", value = "accounting" },
      ]

      secrets = [
        { name = "MYSQL_ROOT_PASSWORD", valueFrom = "${aws_secretsmanager_secret.app.arn}:MYSQL_ROOT_PASSWORD::" },
        { name = "MYSQL_PASSWORD", valueFrom = "${aws_secretsmanager_secret.app.arn}:MYSQL_PASSWORD::" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.db.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "mysql"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "db" {
  name            = "${var.project}-db"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.db.arn
  desired_count   = var.db_desired_count

  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 100
  }

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.db.id]
    assign_public_ip = true # required to reach the internet (pull mysql:8.0) since we have no NAT gateway; SG still blocks all inbound except from the app task
  }

  service_registries {
    registry_arn = aws_service_discovery_service.db.arn
  }
}

resource "aws_ecs_service" "app" {
  name            = "${var.project}-app"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.app_desired_count

  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 100
  }

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = true
  }

  depends_on = [aws_ecs_service.db]
}
