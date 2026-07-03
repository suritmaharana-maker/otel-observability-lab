# EUM / RUM Bolt-On — Complete Handoff & Revival Document

**Purpose:** This document captures the entire state of the EUM (End-User Monitoring / RUM)
bolt-on for the OTel Observability Lab so it can be revived cold — by a fresh chat, a new
machine, or the author after weeks away — and continued from exactly where it was parked.

**Status as of this document:** EUM is **functionally complete and proven on the live
cluster** (full browser→gateway→product-svc→SELECT trace achieved), but **deliberately
parked** as not-yet-prime-time. It is being reserved as an **MIT xPro capstone** component.
The immediate priority is an Optum technical interview (Monday), so EUM is isolated from the
demo path and will be resumed afterward.

**Golden rule for revival:** the source of truth for the frontend code is the author's PC at
`C:\Users\surit\Documents\otel-observability-lab\frontend\` (and, once committed, the GitHub
repo). This document is the *context* to understand and continue that code.

---

## 1. What EUM is and why it was added

The lab already had network (eBPF/Cilium/Hubble), application (OTel SDK), and LLM (gen_ai)
observability. EUM adds the **fourth and final layer: the real end-user's browser experience** —
completing a full-stack, vendor-neutral, "every signal, one trace" story.

The killer capability: ** World Wide Web Consortium (W3C) `traceparent` propagation from the browser to the gateway**, so a
user's click joins the *same trace* as gateway → product-svc → postgres. This turns the lab's
network-blindspot fault demo from a two-view story (app + network) into a **three-view story**:
the user's hung page, the app timeout, and the network POLICY_DENY drop — all in one trace.

---

## 2. Key architectural decisions (the "why", for interview/capstone defense)

1. **Raw OpenTelemetry browser SDK, NOT Grafana Faro.** Deliberate. Faro is a vendor wrapper;
   using it would contradict the lab's vendor-neutral thesis. Same reasoning as rejecting
   OpenLLMetry on the backend. This is the headline decision and a credibility point.
2. **Web Vitals modeled as spans, not metrics.** The browser OTel metrics SDK is less mature;
   emitting LCP/INP/CLS/FCP/TTFB as spans (value in attributes) is current standard RUM practice.
   Noted as a future enhancement (convert to true OTel metrics for time-series dashboards).
3. **RUM is not yet a first-class OTel signal** — modeled as traces + attributes. Honest caveat.
4. **Browser instrumentation is officially experimental** in OTel. Fine for a lab; note for prod.
5. **session.id is the common denominator** across all EUM signals — attached via a custom
   SpanProcessor so it lands on every span (auto and manual), joinable per user session.

**Custom vs standard ratio:** ~70% standard OTel configuration, ~30% custom engineering. The
custom 30% (the parts that show skill): the raw-OTel-over-Faro choice, the click-dedup filter,
the Web-Vitals→span bridge, the SessionSpanProcessor, and the backend workarounds. Honest framing
for interviews: "standard primitives, but I solved real integration problems the out-of-the-box
tooling doesn't handle."

---

## 3. The frontend app — file inventory

Location: `frontend/` in the repo. Files:

- `instrumentation.js` — the OTel browser setup. **This is the heart.** Contains: WebTracerProvider
  (2.x API), OTLP/HTTP exporter, the three auto-instrumentations (document-load, fetch,
  user-interaction), Web Vitals → spans, session context, the custom SessionSpanProcessor, the
  click-dedup filter, ignoreUrls for the collector, and the `traceUserAction()` helper.
- `index.html` — dark "observability console" UI (signal-orange accent). Buttons: /products,
  /recommendations, 10× loop.
- `index.js` — app logic; calls the gateway, drives the loop, surfaces latency/status.
- `package.json` — pinned OTel browser deps + Vite.
- `vite.config.js` — dev server (port 5173) + build config.
- `Dockerfile`, `nginx.conf`, `k8s/frontend.yaml` — for deploying into the cluster (optional;
  NOT currently deployed — the frontend only runs locally via `npm run dev`).
- `README.md` — how it fits, signal flow, config, caveats.

**IMPORTANT — the proven-good `instrumentation.js` (on the author's PC) contains four fixes that
a naive/earlier version does NOT.** Any revived version MUST have all four (see §5).

---

## 4. The full debugging journey — root causes (so mistakes aren't repeated)

Getting a clean end-to-end trace required finding and fixing a chain of issues. Documented here
so a revival doesn't re-fight them:

### 4a. OTel JS 2.x API breaking changes (frontend)
- `Resource` class removed → use `resourceFromAttributes()`.
- `provider.addSpanProcessor()` removed → pass `spanProcessors: [...]` to the WebTracerProvider
  constructor.

### 4b. Cross-Origin Resource Sharing (CORS) (two separate fixes)
- **Collector**: the OTLP/HTTP receiver needed a `cors:` block allowing origin
  `http://localhost:5173` and header `*`. Added to the `otelcol-config` ConfigMap in the
  `observability` namespace, under `receivers.otlp.protocols.http`.
- **Gateway**: FastAPI needed `CORSMiddleware` (allow_origins localhost:5173, allow_headers
  including `traceparent`). Note: `allow_headers=["*"]` was NOT reliable for the traceparent
  header in practice; naming headers explicitly is safer.

### 4c. Wrong collector endpoint on backend services (THE big one)
- **product-svc AND gateway** had `OTEL_EXPORTER_OTLP_ENDPOINT` pointing at
  `http://otelcol-opentelemetry-collector.observability.svc.cluster.local:4317` — an UNREACHABLE
  hostname. Spans failed to export (StatusCode.UNAVAILABLE) and were dropped.
- **Correct endpoint:** `http://otelcol.observability.svc.cluster.local:4317`
- Fixed via `kubectl set env deployment/<svc> -n otel-lab OTEL_EXPORTER_OTLP_ENDPOINT=http://otelcol.observability.svc.cluster.local:4317`
- **CRITICAL revival note:** a pod running BEFORE this fix keeps the old endpoint in memory —
  you MUST restart the deployment after fixing the env var, and confirm the new pod's age.

### 4d. Dynatrace OneAgent fragmenting traces
- gateway and product-svc pods had `dynakube.dynatrace.com/injected: "true"` — OneAgent was
  auto-instrumenting IN PARALLEL with the OTel SDK, splitting one request into multiple trace_ids.
- Fixed by excluding injection: `kubectl patch deployment <svc> -n otel-lab -p` with annotation
  `dynatrace.com/inject: "false"`, then restart.
- **Reconciliation note:** OneAgent was ALSO the thing generating the SELECT db span earlier.
  Removing it revealed product-svc's own psycopg2 instrumentation was NOT producing db spans (see 4f).

### 4e. Browser triple-click (frontend)
- `UserInteractionInstrumentation` emitted 3 click spans for 1 physical click (event-phase
  duplication / a known OTel-js issue). All 3 targeted the same BUTTON.
- **Fix (custom):** a time-dedup filter in `shouldPreventSpanCreation` — a closure suppressing
  duplicate clicks within 300ms. Collapses 3 → 1 while KEEPING the instrumentation (removing it
  entirely was a wrong turn that broke the context chain).

### 4f. Missing SELECT db span (backend)
- product-svc's `Psycopg2Instrumentor().instrument()` was NOT producing db spans (confirmed even
  on a direct in-cluster call, so purely backend — not browser-related). Suspected cause: the
  `RealDictCursor` cursor_factory bypassing auto-instrumentation.
- **Fix (pragmatic workaround):** wrapped the query in `list_products` in an EXPLICIT manual span:
  `with trace.get_tracer("product-svc").start_as_current_span("SELECT products") as span:` with
  db.system/db.statement attributes. `trace` was already imported.
- **HONEST CAVEAT:** this is a workaround. The auto psycopg2 instrumentation still doesn't produce
  spans. A cleaner fix (revisit the cursor_factory instrumentation) is future work.

### 4g. ASGI "http send" noise spans
- gateway and product-svc showed "GET /products http send" spans (asgi.event.type
  http.response.start / http.response.body). These are FastAPIInstrumentor tracing the ASGI
  response lifecycle — noise, not real signal.
- **Fix:** `FastAPIInstrumentor.instrument_app(app, exclude_spans=["send", "receive"])` on BOTH
  gateway and product-svc. Requires a recent instrumentation-fastapi version (0.63b1 has it).

---

## 5. The FOUR fixes the proven `instrumentation.js` must contain

Any revived frontend `instrumentation.js` MUST include all four, or bugs return:

1. **SessionSpanProcessor** — a custom SpanProcessor whose `onStart(span)` sets
   `span.setAttribute('session.id', sessionId)`. Added to `spanProcessors: [ new
   SessionSpanProcessor(), new BatchSpanProcessor(...) ]` (BEFORE BatchSpanProcessor). This is
   what puts session.id on EVERY span (documentLoad, resourceFetch, vitals) uniformly.
2. **Click dedup filter** — `UserInteractionInstrumentation({ shouldPreventSpanCreation: (closure
   with 300ms lastClick dedup) })`. Collapses the triple-click to one.
3. **ignoreUrls on FetchInstrumentation** — to stop tracing the browser's own OTLP export calls
   (though note: the main "http send" noise was actually backend ASGI — see 4g — so this is
   secondary; the backend exclude_spans did the heavy lifting).
4. **BatchSpanProcessor** (not SimpleSpanProcessor) — SimpleSpanProcessor was a debugging choice
   that padded timing and spammed export spans. Batch is correct for clean traces.

---

## 6. Backend changes that live ONLY in cluster ConfigMaps (NOT yet in repo source)

These were applied live via `kubectl edit`/`patch`/`set env` and are NOT reflected in the repo's
`apps/gateway/main.py`, `apps/product-svc/main.py`, or collector config. **To make the repo
accurate, these must be synced back into source files** (deferred — a known TODO):

- **gateway-code ConfigMap** (`otel-lab` ns): added `CORSMiddleware` + `exclude_spans=["send","receive"]`
- **product-svc-code ConfigMap** (`otel-lab` ns): added explicit SELECT span + `exclude_spans` +
  the `query` variable pattern
- **otelcol-config ConfigMap** (`observability` ns): added `cors:` block to OTLP http receiver
- **gateway & product-svc Deployments**: `OTEL_EXPORTER_OTLP_ENDPOINT` corrected;
  `dynatrace.com/inject: "false"` annotation

**Note on demo safety:** these backend changes are demo-SAFE and arguably improvements (cleaner
traces, working SELECT span). CORS is inert unless the browser calls. So the "proven demo"
architecture is not harmed by leaving them in place. Only the frontend (`npm run dev`) is what's
parked — and it simply isn't launched.

---

## 7. How to REVIVE and continue (step by step)

### To bring EUM back up (after the cluster is running):
1. Ensure cluster nodes are up (`aws eks update-nodegroup-config ... desiredSize=2`), all pods
   healthy in `otel-lab` and `observability`.
2. Confirm the backend fixes are still in the ConfigMaps (§6). If the cluster was rebuilt from
   scratch, re-apply them.
3. Port-forward collector and gateway:
   - `kubectl port-forward -n observability daemonset/otelcol 4318:4318`
   - `kubectl port-forward -n otel-lab deploy/gateway 8000:8000`
4. In `frontend/`: `npm install` then `npm run dev` (Vite on :5173).
5. Hard-refresh browser (Ctrl+Shift+R), click /products once.
6. In Dash0: find the trace — expect click → user.products → GET /products (web-frontend) →
   GET /products (gateway, SERVER) → GET /products (gateway, CLIENT, url.full→product-svc) →
   GET /products (product-svc) → SELECT products. One trace, one trace_id.

### If reviving from scratch in a fresh chat:
- This document + the committed `frontend/` folder = everything needed.
- The proven `instrumentation.js` in the repo is authoritative. Verify it has the four fixes (§5).
- The debugging root causes (§4) explain every non-obvious fix so they aren't re-fought.

---

## 8. Planned enhancements (the capstone backlog — where this is headed)

- **Network signal fully stitched into EUM traces.** Currently EUM (app-layer) is done, but the
  network (Hubble/eBPF POLICY_DENY) signals are captured ALONGSIDE, not INSIDE, the same trace
  waterfall. The vision: one click that hangs, traced from browser to the POLICY_DENY drop. This
  needs eBPF trace-context correlation — the final piece of "every signal, one trace."
- **Web Vitals as true OTel metrics** (not spans) → proper p75 time-series dashboards like
  Datadog/Dynatrace RUM.
- **session.id propagated to BACKEND spans via OTel baggage** — currently session.id is on browser
  spans only; trace_id propagates but session.id doesn't. Baggage would make session.id a true
  stack-wide join key.
- **Fault injection at the browser/edge (Fault 0)** — throttle browser network (DevTools Slow 3G)
  → degraded LCP/TTFB in vitals. The RUM-specific fault the backend-only setup couldn't do.
- **Clean fix for the psycopg2 db span** (replace the explicit-span workaround from §4f).
- **Deploy the frontend into the cluster** (Dockerfile + k8s/frontend.yaml exist) for a fully
  hosted demo rather than local `npm run dev`.

---

## 9. Fault injection: before vs after EUM (for demo/capstone narrative)

**Before EUM (backend-only):** entry point was a synthetic load script; faults (gateway,
network-policy, database) were observed from the MIDDLE of the stack outward. No user perspective.

**After EUM (user-origin):** the trace starts at the browser. A NEW edge fault (Fault 0:
browser/network throttle) is now possible, AND every backend fault is observed from the USER
inward — which is how real incidents are reported ("the page is slow") and diagnosed (trace down
to the failing layer). Faults:
- Fault 0 (edge): DevTools network throttle → degraded LCP/TTFB.
- Fault A (gateway): scale to 0 / add latency → browser fetch fails, user sees hung page.
- Fault B (network policy — signature demo): CiliumNetworkPolicy blocks gateway→product-svc →
  trace shows click → gateway → hang → POLICY_DENY. Three views: user, app, network.
- Fault C (database): slow/kill query → visible in the (explicit) SELECT span, traced to the click.

---

## 10. One-paragraph summary (for a fresh chat to get oriented fast)

The EUM bolt-on adds a raw-OpenTelemetry browser client (frontend/) to the OTel Observability
Lab, propagating W3C traceparent to the gateway so a user's click joins the same trace as
gateway→product-svc→postgres. It is functionally complete and proven (clean end-to-end trace in
Dash0), but parked as MIT-xPro-capstone material while the author prioritizes an Optum interview.
Getting it working required fixing OTel-JS-2.x API changes, two CORS layers, a wrong collector
endpoint on the backend services, Dynatrace OneAgent trace fragmentation, a browser triple-click
(fixed with a 300ms dedup filter), a missing psycopg2 SELECT span (fixed with an explicit manual
span), and ASGI noise spans (fixed with exclude_spans). The proven frontend instrumentation.js
has four required fixes: SessionSpanProcessor, click-dedup, ignoreUrls, BatchSpanProcessor.
Backend changes currently live only in cluster ConfigMaps and are a TODO to sync into repo source.
Next major work: stitch the network (eBPF POLICY_DENY) signal INTO the EUM trace for a true
"every signal, one trace" full-stack demo.
