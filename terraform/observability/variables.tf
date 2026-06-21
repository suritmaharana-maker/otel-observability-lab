# =============================================================================
# Variables — Observability Module
# =============================================================================

# --- Cluster connection (passed from eks module outputs) ---

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

# --- Backend selection ---
#
# This is the key variable for the multi-cloud, multi-backend vision.
# Add "datadog" to enable Datadog in Phase 7.
# Example: backends = ["dash0", "dynatrace", "datadog"]

variable "backends" {
  description = "List of active observability backends"
  type        = list(string)
  default     = ["dash0"]

  validation {
    condition = alltrue([
      for b in var.backends : contains(["dash0", "dynatrace", "datadog"], b)
    ])
    error_message = "backends must be one or more of: dash0, dynatrace, datadog"
  }
}

# --- Dash0 credentials ---

variable "dash0_auth_token" {
  description = "Dash0 auth token for OTLP ingest"
  type        = string
  sensitive   = true
  default     = ""
}

# --- Dynatrace credentials ---

variable "dynatrace_environment_id" {
  description = "Dynatrace environment ID (e.g. yta61562)"
  type        = string
  default     = ""
}

variable "dynatrace_api_token" {
  description = "Dynatrace API token — needs: metrics.ingest, logs.ingest, openTelemetryTrace.ingest, DataExport, problems.read, entities.read"
  type        = string
  sensitive   = true
  default     = ""
}

variable "dynatrace_operator_token" {
  description = "Dynatrace operator token — needs: operator, InstallerDownload scopes"
  type        = string
  sensitive   = true
  default     = ""
}

# --- Datadog credentials (Phase 7) ---

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
