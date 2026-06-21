receivers:
  otlp:
    protocols:
      grpc:
        endpoint: "0.0.0.0:4317"
      http:
        endpoint: "0.0.0.0:4318"

  hostmetrics:
    collection_interval: 30s
    root_path: /hostfs
    scrapers:
      cpu: {}
      memory: {}
      disk: {}
      network: {}

  prometheus/hubble:
    config:
      scrape_configs:
        - job_name: "hubble-metrics"
          scrape_interval: 30s
          static_configs:
            - targets: ["hubble-metrics.kube-system.svc.cluster.local:9965"]
          metric_relabel_configs:
            - source_labels: [__name__]
              regex: "hubble_.*"
              action: keep

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
    spike_limit_mib: 128
  batch:
    send_batch_size: 1000
    timeout: 10s
  resource:
    attributes:
      - key: deployment.environment
        value: "lab"
        action: upsert
      - key: cloud.provider
        value: "aws"
        action: upsert
      - key: cloud.region
        value: "us-east-2"
        action: upsert

exporters:
%{ if dash0_enabled ~}
  otlp/dash0:
    endpoint: "ingress.us-west-2.aws.dash0.com:4317"
    auth:
      authenticator: bearertokenauth/dash0
%{ endif ~}
%{ if dynatrace_enabled ~}
  otlphttp/dynatrace:
    endpoint: "https://${dynatrace_environment_id}.live.dynatrace.com/api/v2/otlp"
    headers:
      Authorization: "Api-Token $${env:DT_API_TOKEN}"
%{ endif ~}
  debug:
    verbosity: basic

extensions:
%{ if dash0_enabled ~}
  bearertokenauth/dash0:
    scheme: Bearer
    token: "$${env:DASH0_AUTH_TOKEN}"
%{ endif ~}

service:
  extensions: [%{ if dash0_enabled }bearertokenauth/dash0%{ endif }]
  pipelines:
    metrics:
      receivers: [otlp, hostmetrics, prometheus/hubble]
      processors: [memory_limiter, resource, batch]
      exporters: [%{ if dash0_enabled }otlp/dash0%{ endif }%{ if dash0_enabled && dynatrace_enabled }, %{ endif }%{ if dynatrace_enabled }otlphttp/dynatrace%{ endif }]
    traces:
      receivers: [otlp]
      processors: [memory_limiter, resource, batch]
      exporters: [%{ if dash0_enabled }otlp/dash0%{ endif }%{ if dash0_enabled && dynatrace_enabled }, %{ endif }%{ if dynatrace_enabled }otlphttp/dynatrace%{ endif }, debug]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, resource, batch]
      exporters: [%{ if dash0_enabled }otlp/dash0%{ endif }%{ if dash0_enabled && dynatrace_enabled }, %{ endif }%{ if dynatrace_enabled }otlphttp/dynatrace%{ endif }, debug]
