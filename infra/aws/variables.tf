variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Short name used as a prefix for all resources"
  type        = string
  default     = "vithana"
}

variable "mysql_root_password" {
  description = "MySQL root password"
  type        = string
  sensitive   = true
}

variable "mysql_password" {
  description = "MySQL app-user password"
  type        = string
  sensitive   = true
}

variable "jwt_secret_key" {
  type      = string
  sensitive = true
}

variable "admin_api_key" {
  type      = string
  sensitive = true
}

variable "integration_encryption_key" {
  type      = string
  sensitive = true
}

variable "llm_api_key" {
  description = "OpenAI (or configured provider) API key"
  type        = string
  sensitive   = true
}

variable "llamaparse_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "google_client_id" {
  type    = string
  default = ""
}

variable "google_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "app_image" {
  description = "Full ECR image URI:tag for the combined frontend+backend App Runner image. Leave blank on first apply (ECR repo is created first, then push, then set this)."
  type        = string
  default     = ""
}

variable "s3_bucket_name" {
  description = "S3 bucket name for invoice attachment storage (App Runner has no persistent volume, unlike the EFS-backed Fargate setup this replaced)."
  type        = string
  default     = ""
}

variable "apprunner_cpu" {
  description = "App Runner vCPU units: 1024 (1 vCPU), 2048 (2 vCPU), etc."
  type        = string
  default     = "1024"
}

variable "apprunner_memory" {
  description = "App Runner memory in MB: must be a valid App Runner cpu/memory combination."
  type        = string
  default     = "3072"
}

variable "db_desired_count" {
  description = "0 = asleep (no compute billed). Set to 1 to wake. Must be woken/slept together with the App Runner service via the wake.sh/sleep.sh scripts."
  type        = number
  default     = 0
}

variable "log_retention_days" {
  type    = number
  default = 3
}
