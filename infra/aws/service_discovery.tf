# Lets the app task resolve the db task by a stable DNS name
# (db.vithana.internal) even though each task gets a fresh IP on wake.
# Cost: $0.10/month per namespace, negligible per-lookup fee.

resource "aws_service_discovery_private_dns_namespace" "internal" {
  name = "${var.project}.internal"
  vpc  = data.aws_vpc.default.id
}

resource "aws_service_discovery_service" "db" {
  name = "db"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.internal.id
    dns_records {
      ttl  = 10
      type = "A"
    }
    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}
