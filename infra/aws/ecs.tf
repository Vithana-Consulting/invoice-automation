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

resource "aws_cloudwatch_log_group" "db" {
  name              = "/ecs/${var.project}/db"
  retention_in_days = var.log_retention_days
}

# --- db task: MySQL 8.0, official image, data on EFS ---
# The app tier (frontend+backend) moved to App Runner (see apprunner.tf) —
# App Runner has no persistent-volume equivalent, so MySQL stays here on
# Fargate where it can keep its EFS-backed data volume.
resource "aws_ecs_task_definition" "db" {
  family                   = "${var.project}-db"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

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
      name         = "mysql"
      image        = "mysql:8.0"
      essential    = true
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
    assign_public_ip = true # required to reach the internet (pull mysql:8.0) since we have no NAT gateway — also now how App Runner reaches it, via the fixed Elastic IP in eip.tf
  }
}
