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

variable "allowed_cidr" {
  description = "CIDR block allowed to reach the app on 3000/8000. Restrict this to your office/VPN IP for an internal tool."
  type        = string
  default     = "0.0.0.0/0"
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

variable "backend_image" {
  description = "Full ECR image URI:tag for the backend. Leave blank on first apply (ECR repo is created first, then push, then set this)."
  type        = string
  default     = ""
}

variable "frontend_image" {
  description = "Full ECR image URI:tag for the frontend."
  type        = string
  default     = ""
}

variable "caddy_image" {
  description = "Full ECR image URI:tag for the Caddy TLS front door."
  type        = string
  default     = ""
}

variable "app_desired_count" {
  description = "0 = asleep (no charge for compute). Set to 1 to wake."
  type        = number
  default     = 0
}

variable "db_desired_count" {
  description = "0 = asleep. Set to 1 to wake. Must be woken together with the app service."
  type        = number
  default     = 0
}

variable "log_retention_days" {
  type    = number
  default = 3
}
