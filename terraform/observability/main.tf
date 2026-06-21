# =============================================================================
# OTel Observability Lab — Observability Module
# VERSION COMPATIBILITY (verified June 20, 2026):
#   terraform:               >= 1.15.6
#   hashicorp/kubernetes:    ~> 2.36.0  (installed: 2.36.0)
#   hashicorp/helm:          ~> 2.17.0  (installed: 2.17.0)
#   dynatrace-oss/dynatrace: ~> 1.97.0  (installed: 1.97.2)
#
# TOKEN SCOPES VERIFIED from Terraform Registry docs:
#   dynatrace_service_anomalies_v2: settings.read + settings.write
#   OTel Collector ingest:          metrics.ingest + logs.ingest +
#                                   openTelemetryTrace.ingest + DataExport
#   Problems API (/diagnose):       problems.read + entities.read
#   OneAgent operator:              operator + InstallerDownload
#
# SCHEMA VERIFIED via terraform validate:
#   load_drops + load_spikes blocks required by provider 1.97.2
#   Semicolons not valid in HCL — all blocks fully expanded
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
      match_labels = {
        app = "otelcol"
      }
    }

    template {
      metadata {
        labels = {
          app = "otelcol"
        }
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
# DYNATRACE ONEA GENT
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
      metadataEnrichment = {
        enabled = true
      }
      oneAgent = {
        cloudNativeFullStack = {
          namespaceSelector = {
            matchLabels = {
              "dynatrace-monitor" = "true"
            }
          }
        }
      }
      activeGate = {
        capabilities = ["kubernetes-monitoring", "routing"]
      }
    }
  }
  depends_on = [
    kubernetes_secret.dynakube,
    helm_release.dynatrace_operator,
  ]
}

# =============================================================================
# DYNATRACE ANOMALY DETECTION
#
# Verified token scopes: settings.read + settings.write
# Verified required blocks (via terraform validate): load_drops + load_spikes
# scope = "environment" applies to ALL services
# Fixed thresholds bypass 7-day baselining requirement
# =============================================================================

resource "dynatrace_service_anomalies_v2" "environment_defaults" {
  count = local.dynatrace_enabled ? 1 : 0
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

  load_drops {
    enabled = false
  }

  load_spikes {
    enabled = false
  }
}
