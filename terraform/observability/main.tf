# =============================================================================
# OTel Observability Lab — Observability Module
# Manages: OTel Collector, Beyla, Dynatrace OneAgent, secrets, namespaces
#
# VERSION COMPATIBILITY (verified June 20, 2026):
#   terraform:               >= 1.15.6
#   hashicorp/kubernetes:    ~> 2.36.0
#   hashicorp/helm:          ~> 2.17.0
#   dynatrace-oss/dynatrace: ~> 1.97.0 (latest: 1.97.2, published June 10 2026)
#
# TOKEN SCOPES REQUIRED (verified from Terraform Registry docs):
#   dynatrace_service_anomalies_v2: settings.read + settings.write
#   dynatrace OneAgent ingest:      metrics.ingest + logs.ingest +
#                                   openTelemetryTrace.ingest + DataExport
#   problems.read:                  for /diagnose?backend=dynatrace in llm-svc
#
# WHY Terraform vs Ansible:
#   Terraform  = RESOURCES (namespaces, secrets, DaemonSets, Helm releases,
#                           Dynatrace anomaly thresholds) — stateful, tracked
#   Ansible    = OPERATIONS (IMDSv2 hop limit fix) — runs against live instances,
#                not a resource, changes every ASG replacement
# =============================================================================

terraform {
  required_version = ">= 1.15.6"

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.36.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.17.0"
    }
    dynatrace = {
      # Official Dynatrace provider — supported by Dynatrace Inc.
      # Registry: registry.terraform.io/providers/dynatrace-oss/dynatrace
      # Latest: 1.97.2 (June 10, 2026)
      source  = "dynatrace-oss/dynatrace"
      version = "~> 1.97.0"
    }
  }
}

# =============================================================================
# PROVIDERS
# =============================================================================

provider "kubernetes" {
  host                   = var.cluster_endpoint
  cluster_ca_certificate = base64decode(var.cluster_ca_certificate)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", var.cluster_name, "--region", var.aws_region]
  }
}

provider "helm" {
  kubernetes {
    host                   = var.cluster_endpoint
    cluster_ca_certificate = base64decode(var.cluster_ca_certificate)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", var.cluster_name, "--region", var.aws_region]
    }
  }
}

# Dynatrace provider
# Verified auth variable names from docs: dt_env_url and dt_api_token
# Token must have: settings.read + settings.write (for anomaly detection)
provider "dynatrace" {
  dt_env_url   = "https://${var.dynatrace_environment_id}.live.dynatrace.com"
  dt_api_token = var.dynatrace_settings_token
}

# =============================================================================
# LOCALS
# =============================================================================

locals {
  dash0_enabled     = contains(var.backends, "dash0")
  dynatrace_enabled = contains(var.backends, "dynatrace")
  datadog_enabled   = contains(var.backends, "datadog")

  otelcol_config = templatefile("${path.module}/templates/otelcol-config.yaml.tpl", {
    dash0_enabled            = local.dash0_enabled
    dynatrace_enabled        = local.dynatrace_enabled
    dynatrace_environment_id = var.dynatrace_environment_id
  })

  common_labels = {
    "app.kubernetes.io/managed-by" = "terraform"
    "project"                      = "otel-observability-lab"
    "environment"                  = var.environment
  }
}

# =============================================================================
# NAMESPACE LABELS
# =============================================================================

resource "kubernetes_labels" "otel_lab_dynatrace" {
  count       = local.dynatrace_enabled ? 1 : 0
  api_version = "v1"
  kind        = "Namespace"
  metadata {
    name = "otel-lab"
  }
  labels = {
    "dynatrace-monitor" = "true"
  }
}

# =============================================================================
# SECRETS
# Secret VALUES are passed as sensitive variables — never hardcoded.
# Values provided via TF_VAR_ environment variables or terraform.tfvars (gitignored).
# =============================================================================

resource "kubernetes_secret" "dash0" {
  count = local.dash0_enabled ? 1 : 0
  metadata {
    name      = "dash0-secret"
    namespace = "observability"
    labels    = local.common_labels
  }
  data = {
    "auth-token" = var.dash0_auth_token
  }
  type = "Opaque"
}

# llm-svc reads dash0-secret from otel-lab namespace
resource "kubernetes_secret" "dash0_otel_lab" {
  count = local.dash0_enabled ? 1 : 0
  metadata {
    name      = "dash0-secret"
    namespace = "otel-lab"
    labels    = local.common_labels
  }
  data = {
    "auth-token" = var.dash0_auth_token
  }
  type = "Opaque"
}

resource "kubernetes_secret" "dynatrace" {
  count = local.dynatrace_enabled ? 1 : 0
  metadata {
    name      = "dynatrace-secret"
    namespace = "observability"
    labels    = local.common_labels
  }
  data = {
    "api-token"      = var.dynatrace_ingest_token
    "environment-id" = var.dynatrace_environment_id
  }
  type = "Opaque"
}

# =============================================================================
# OTEL COLLECTOR CONFIGMAP
# Rendered from template — exporters included/excluded based on backends variable
# =============================================================================

resource "kubernetes_config_map" "otelcol" {
  metadata {
    name      = "otelcol-config"
    namespace = "observability"
    labels    = local.common_labels
  }
  data = {
    "config.yaml" = local.otelcol_config
  }
}

# =============================================================================
# OTEL COLLECTOR DAEMONSET
# =============================================================================

resource "kubernetes_daemon_set_v1" "otelcol" {
  metadata {
    name      = "otelcol"
    namespace = "observability"
    labels    = merge(local.common_labels, { app = "otelcol" })
  }

  spec {
    selector {
      match_labels = { app = "otelcol" }
    }

    template {
      metadata {
        labels = { app = "otelcol" }
      }

      spec {
        service_account_name = "otelcol"

        toleration {
          effect   = "NoSchedule"
          operator = "Exists"
        }
        toleration {
          effect   = "NoExecute"
          operator = "Exists"
        }

        container {
          name  = "otelcol"
          image = "otel/opentelemetry-collector-contrib:0.154.0"
          args  = ["--config=/conf/config.yaml"]

          security_context {
            run_as_user = 0
          }

          resources {
            limits = {
              cpu    = "500m"
              memory = "512Mi"
            }
            requests = {
              cpu    = "100m"
              memory = "128Mi"
            }
          }

          dynamic "env" {
            for_each = local.dash0_enabled ? [1] : []
            content {
              name = "DASH0_AUTH_TOKEN"
              value_from {
                secret_key_ref {
                  name = kubernetes_secret.dash0[0].metadata[0].name
                  key  = "auth-token"
                }
              }
            }
          }

          dynamic "env" {
            for_each = local.dynatrace_enabled ? [1] : []
            content {
              name = "DT_API_TOKEN"
              value_from {
                secret_key_ref {
                  name = kubernetes_secret.dynatrace[0].metadata[0].name
                  key  = "api-token"
                }
              }
            }
          }

          dynamic "env" {
            for_each = local.dynatrace_enabled ? [1] : []
            content {
              name = "DT_ENVIRONMENT_ID"
              value_from {
                secret_key_ref {
                  name = kubernetes_secret.dynatrace[0].metadata[0].name
                  key  = "environment-id"
                }
              }
            }
          }

          env {
            name = "MY_POD_IP"
            value_from {
              field_ref {
                field_path = "status.podIP"
              }
            }
          }

          volume_mount {
            name       = "config"
            mount_path = "/conf"
          }

          volume_mount {
            name              = "hostfs"
            mount_path        = "/hostfs"
            read_only         = true
            mount_propagation = "HostToContainer"
          }
        }

        volume {
          name = "config"
          config_map {
            name = kubernetes_config_map.otelcol.metadata[0].name
          }
        }

        volume {
          name = "hostfs"
          host_path {
            path = "/"
          }
        }
      }
    }
  }

  depends_on = [
    kubernetes_config_map.otelcol,
    kubernetes_secret.dash0,
    kubernetes_secret.dynatrace,
  ]
}

# =============================================================================
# DYNATRACE ONEA GENT — Helm release
#
# Verified: DynaKube v1beta6 is correct API version (checked against our cluster)
# Helm chart: dynatrace-operator (stable repo)
# Requires: operator token with 'operator' + 'InstallerDownload' scopes
# =============================================================================

resource "kubernetes_namespace" "dynatrace" {
  count = local.dynatrace_enabled ? 1 : 0
  metadata {
    name   = "dynatrace"
    labels = local.common_labels
  }
}

resource "helm_release" "dynatrace_operator" {
  count      = local.dynatrace_enabled ? 1 : 0
  name       = "dynatrace-operator"
  repository = "https://raw.githubusercontent.com/Dynatrace/dynatrace-operator/main/config/helm/repos/stable"
  chart      = "dynatrace-operator"
  namespace  = kubernetes_namespace.dynatrace[0].metadata[0].name
  timeout    = 300
  depends_on = [kubernetes_namespace.dynatrace]
}

resource "kubernetes_secret" "dynakube" {
  count = local.dynatrace_enabled ? 1 : 0
  metadata {
    name      = "dynakube"
    namespace = kubernetes_namespace.dynatrace[0].metadata[0].name
    labels    = local.common_labels
  }
  data = {
    apiToken        = var.dynatrace_operator_token
    dataIngestToken = var.dynatrace_ingest_token
  }
  type       = "Opaque"
  depends_on = [helm_release.dynatrace_operator]
}

# DynaKube CR — Cloud Native Full Stack
# Verified: v1beta6 is correct (checked kubectl get crd dynakubes.dynatrace.com)
resource "kubernetes_manifest" "dynakube" {
  count = local.dynatrace_enabled ? 1 : 0
  manifest = {
    apiVersion = "dynatrace.com/v1beta6"
    kind       = "DynaKube"
    metadata = {
      name      = "dynakube"
      namespace = kubernetes_namespace.dynatrace[0].metadata[0].name
      annotations = {
        "feature.dynatrace.com/automatic-kubernetes-api-monitoring" = "true"
      }
    }
    spec = {
      apiUrl = "https://${var.dynatrace_environment_id}.live.dynatrace.com/api"
      metadataEnrichment = { enabled = true }
      oneAgent = {
        cloudNativeFullStack = {
          namespaceSelector = {
            matchLabels = { "dynatrace-monitor" = "true" }
          }
        }
      }
      activeGate = {
        capabilities = ["kubernetes-monitoring", "routing"]
      }
    }
  }
  depends_on = [kubernetes_secret.dynakube, helm_release.dynatrace_operator]
}

# =============================================================================
# DYNATRACE ANOMALY DETECTION
#
# Verified token scopes (from Terraform Registry, June 2026):
#   dynatrace_service_anomalies_v2 requires: settings.read + settings.write
#   These are DIFFERENT from ingest token — use dynatrace_settings_token variable
#
# Scope "environment" applies to ALL services — no service entity ID lookup needed.
# This avoids the need for a dynatrace_service data source (which does not exist).
#
# Fixed thresholds bypass the "20% of 7 days" baselining requirement.
# =============================================================================

resource "dynatrace_service_anomalies_v2" "environment_defaults" {
  count = local.dynatrace_enabled ? 1 : 0

  # "environment" scope = applies to all services
  # No service entity ID needed — works immediately without baseline
  scope = "environment"

  failure_rate {
    enabled        = true
    detection_mode = "fixed"
    fixed_detection {
      sensitivity = "high"
      threshold   = 5
      over_alerting_protection {
        minutes_abnormal_state = 1
        requests_per_minute    = 1
      }
    }
  }

  response_time {
    enabled        = true
    detection_mode = "fixed"
    fixed_detection {
      sensitivity = "high"
      over_alerting_protection {
        minutes_abnormal_state = 1
        requests_per_minute    = 1
      }
      response_time_all {
        degradation_milliseconds = 2000
      }
      response_time_slowest {
        slowest_degradation_milliseconds = 4000
      }
    }
  }
}
