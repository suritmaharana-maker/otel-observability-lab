# =============================================================================
# Variables — Observability Module
#
# TOKEN ARCHITECTURE (two separate DT tokens — different scopes):
#
#   dynatrace_ingest_token:
#     Used by: OTel Collector DaemonSet, llm-svc /diagnose
#     Scopes: metrics.ingest, logs.ingest, openTelemetryTrace.ingest,
#             DataExport, problems.read, entities.read
#     In Dynatrace UI: "OTel_API_Token_v2"
#
#   dynatrace_settings_token:
#     Used by: Terraform provider (dynatrace_service_anomalies_v2)
#     Scopes: settings.read, settings.write
#     In Dynatrace UI: create new token named "terraform-settings"
#     NOTE: Cannot be same as ingest token — different scope family
#
#   dynatrace_operator_token:
#     Used by: DynaKube secret (OneAgent operator)
#     Scopes: operator (Kubernetes Operator), InstallerDownload
#     In Dynatrace UI: "dynatrace-operator" token (already exists)
# =============================================================================

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
}

variable "cluster_endpoint" {
  description = "EKS cluster API endpoint"
  type        = string
}

variable "cluster_ca_certificate" {
  description = "Base64 encoded cluster CA certificate"
  type        = string
  sensitive   = true
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "lab"
}

# Backend selection
# Terraform validates this at plan time — typos caught before apply
variable "backends" {
  description = "Active observability backends. Add 'datadog' for Phase 7."
  type        = list(string)
  default     = ["dash0"]

  validation {
    condition = alltrue([
      for b in var.backends : contains(["dash0", "dynatrace", "datadog"], b)
    ])
    error_message = "Each backend must be one of: dash0, dynatrace, datadog"
  }
}

# Dash0
variable "dash0_auth_token" {
  description = "Dash0 auth token. Get from: Dash0 console → Organization → Auth tokens"
  type        = string
  sensitive   = true
  default     = ""
}

# Dynatrace — three separate tokens, three separate purposes
variable "dynatrace_environment_id" {
  description = "Dynatrace environment ID (e.g. yta61562)"
  type        = string
  default     = ""
}

variable "dynatrace_ingest_token" {
  description = <<-EOF
    Dynatrace token for OTLP ingest + Problems API read.
    Required scopes: metrics.ingest, logs.ingest, openTelemetryTrace.ingest,
                     DataExport, problems.read, entities.read
    Create in DT UI as: OTel_API_Token_v2
  EOF
  type        = string
  sensitive   = true
  default     = ""
}

variable "dynatrace_settings_token" {
  description = <<-EOF
    Dynatrace token for Terraform settings management.
    Required scopes: settings.read, settings.write
    Used by: dynatrace_service_anomalies_v2 resource
    DIFFERENT from ingest token — settings.* scopes are separate scope family
    Create in DT UI as: terraform-settings
  EOF
  type        = string
  sensitive   = true
  default     = ""
}

variable "dynatrace_operator_token" {
  description = <<-EOF
    Dynatrace operator token for OneAgent installation.
    Required scopes: operator (Kubernetes Operator), InstallerDownload
    Already exists in DT UI as: dynatrace-operator
  EOF
  type        = string
  sensitive   = true
  default     = ""
}

# Datadog (Phase 7 — stub)
variable "datadog_api_key" {
  description = "Datadog API key (Phase 7)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "datadog_site" {
  description = "Datadog site (e.g. datadoghq.com)"
  type        = string
  default     = "datadoghq.com"
}
