# OTel Lab — Frontend (EUM / RUM layer)

A minimal but real browser client that completes the lab's signal coverage: **end-user
monitoring (EUM)** on top of network (eBPF), application (OTel SDK), and LLM (gen_ai)
observability. Instrumented with the **raw OpenTelemetry browser SDK** — deliberately
**not** a vendor wrapper (e.g. Grafana Faro) — to keep the pipeline vendor-neutral and
consistent with how the backend is instrumented.

## Why this exists

The backend services prove the *network blindspot* — when a CiliumNetworkPolicy blocks
gateway → product-svc, the app sees a timeout and the network layer shows the POLICY_DENY
drop. This frontend adds the **third view: the user's**. Because the browser propagates the
W3C `traceparent` header to the gateway, a user's click joins the *same trace* as
gateway → product-svc → postgres. So the fault is now visible as **a real user's page
hanging**, traced end-to-end down to the network drop.

## What it captures

- **Document load** timings (page load, resource waterfall)
- **Fetch spans** for every gateway call, with `traceparent` propagation (the end-to-end stitch)
- **User-interaction** spans (clicks)
- **Core Web Vitals** (LCP, INP, CLS, FCP, TTFB) as OTel spans with good/needs-improvement/poor ratings
- **Session context** (`session.id`, browser, device) on every span
- **Unhandled errors / promise rejections**

All exported via **OTLP/HTTP → the OTel Collector → Dash0 / Dynatrace**. No new pipeline,
no new backend.

## Signal flow

```
 user click
    │  (user.<action> span)
    ▼
 fetch → gateway        ──traceparent──►  gateway → product-svc → postgres
    │  (HTTP span)                              (same trace_id)
    ▼
 OTLP/HTTP → OTel Collector → Dash0 / Dynatrace
```

## Files

- `instrumentation.js` — the OTel browser setup (load first). Tracer provider, OTLP exporter,
  auto-instrumentations, Web Vitals, session context, `traceUserAction()` helper.
- `index.html` — the console UI (an observability control surface, not a store).
- `index.js` — app logic: calls the gateway, surfaces latency/status, drives the steady-load loop.
- `package.json` — pinned OTel browser deps + Vite build.

## Configuration

Inject at runtime (e.g. via a `<script>` before the module, or build-time env):

```html
<script>
  window.__GATEWAY_URL__ = "https://<your-elb-host>";        // gateway base
  window.__OTEL_COLLECTOR_URL__ = "https://<collector>/v1/traces"; // OTLP/HTTP traces
</script>
```

Defaults assume local port-forwards: gateway `localhost:8000`, collector `localhost:4318`.

> **CORS note:** the gateway and collector must allow the browser origin and the
> `traceparent` request header (Access-Control-Allow-Headers). For the lab, enable permissive
> CORS on the gateway's `/products` and `/recommendations` routes and on the collector's
> OTLP/HTTP receiver. This is the most common first-run snag.

## Run locally (against port-forwards)

```bash
npm install
# port-forward the gateway and collector in separate shells:
#   kubectl port-forward deploy/gateway -n otel-lab 8000:8000
#   kubectl port-forward deploy/otel-collector -n otel-lab 4318:4318
npm run dev          # vite dev server, open the printed URL
```

Click **/products**, then inject the CiliumNetworkPolicy fault and click again — the request
hangs, the console shows it failing from the user's side, and the trace (browser → gateway →
drop) lands in Dash0.

## Deploy into the cluster (optional)

Build the static bundle and serve it (nginx pod, or any static host). A `Dockerfile` and
`k8s/frontend.yaml` can wrap `npm run build` output in an nginx image and expose it via the
existing ELB. Keep it in the `otel-lab` namespace so its spans share the pipeline.

## Honest status

- Browser instrumentation is officially **experimental** in OpenTelemetry — works well and is
  widely used, but the spec isn't finalized. Fine for a lab; note the caveat for production.
- RUM is **not yet a first-class OTel signal** — vitals/interactions are modeled as spans +
  attributes (current standard practice).
- Pin the `@opentelemetry/*` core packages to one compatible release cycle before building
  (same discipline as the backend's VERSIONS.md).
