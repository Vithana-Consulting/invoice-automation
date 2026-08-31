# Persistent storage for Fargate (which has no local disk that survives a
# task restart). Billed per GB actually stored, no fixed per-mount charge.

resource "aws_efs_file_system" "data" {
  creation_token  = "${var.project}-data"
  encrypted       = true
  throughput_mode = "bursting"

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = { Project = var.project }
}

resource "aws_efs_mount_target" "data" {
  for_each        = toset(data.aws_subnets.default.ids)
  file_system_id  = aws_efs_file_system.data.id
  subnet_id       = each.value
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_access_point" "mysql_data" {
  file_system_id = aws_efs_file_system.data.id

  posix_user {
    uid = 999 # mysql user in the official mysql:8.0 image
    gid = 999
  }

  root_directory {
    path = "/mysql-data"
    creation_info {
      owner_uid   = 999
      owner_gid   = 999
      permissions = "755"
    }
  }

  tags = { Project = var.project, Purpose = "mysql-data" }
}

# Attachments moved to S3 (see s3.tf) — App Runner has no EFS-equivalent
# mount, unlike the Fargate app task this replaced.
