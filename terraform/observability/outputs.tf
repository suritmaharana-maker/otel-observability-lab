output "otelcol_configmap_name" {
  description = "OTel Collector ConfigMap name"
  value       = kubernetes_config_map.otelcol.metadata[0].name
}

output "active_backends" {
  description = "List of active observability backends"
  value       = var.backends
}

output "dynatrace_enabled" {
  description = "Whether Dynatrace backend is enabled"
  value       = local.dynatrace_enabled
}

output "dash0_enabled" {
  description = "Whether Dash0 backend is enabled"
  value       = local.dash0_enabled
}
