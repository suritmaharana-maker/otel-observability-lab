// instrumentation.js
// Raw OpenTelemetry browser instrumentation for the OTel Observability Lab frontend.
// Deliberately NOT using a vendor wrapper (e.g. Grafana Faro) — keeps the pipeline
// vendor-neutral and consistent with how the backend is instrumented (bare OTel SDK).
//
// Flow:  browser spans  ->  OTLP/HTTP  ->  OTel Collector  ->  Dash0 / Dynatrace
// Trace context (W3C traceparent) is propagated to the gateway so a user's click
// joins the SAME trace as gateway -> product-svc -> postgres -> (POLICY_DENY drop).
//
// Load this BEFORE any application code so all interactions are captured from the start.

import { WebTracerProvider } from '@opentelemetry/sdk-trace-web';
import { BatchSpanProcessor } from '@opentelemetry/sdk-trace-base';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { ZoneContextManager } from '@opentelemetry/context-zone';
import { W3CTraceContextPropagator } from '@opentelemetry/core';
import { Resource } from '@opentelemetry/resources';
import { registerInstrumentations } from '@opentelemetry/instrumentation';
import { DocumentLoadInstrumentation } from '@opentelemetry/instrumentation-document-load';
import { FetchInstrumentation } from '@opentelemetry/instrumentation-fetch';
import { UserInteractionInstrumentation } from '@opentelemetry/instrumentation-user-interaction';
import { trace, context } from '@opentelemetry/api';
import { onLCP, onINP, onCLS, onFCP, onTTFB } from 'web-vitals';

// ---- Configuration -----------------------------------------------------------
// The Collector's OTLP/HTTP traces endpoint. In the lab this is exposed via the
// gateway/ELB or a dedicated collector route. Override at build time if needed.
const COLLECTOR_TRACES_URL =
  window.__OTEL_COLLECTOR_URL__ || 'http://localhost:4318/v1/traces';

// The gateway origin(s) that should receive the W3C traceparent header.
// This is what stitches browser spans to backend spans. Adjust to your ELB host.
const GATEWAY_URLS = [
  /localhost:8000/,
  /\.elb\.amazonaws\.com/,
];

const SERVICE_NAME = 'web-frontend';
const SERVICE_VERSION = '0.1.0';

// ---- Session + user context --------------------------------------------------
// RUM data is only actionable when you can slice by session. Generate a stable
// per-session id and attach browser/device context to every span.
function getSessionId() {
  let id = sessionStorage.getItem('otel_session_id');
  if (!id) {
    id = (crypto.randomUUID && crypto.randomUUID()) ||
      String(Date.now()) + Math.random().toString(16).slice(2);
    sessionStorage.setItem('otel_session_id', id);
  }
  return id;
}

const sessionId = getSessionId();

const resource = new Resource({
  'service.name': SERVICE_NAME,
  'service.version': SERVICE_VERSION,
  'telemetry.sdk.language': 'webjs',
  // browser.* attributes mark this as a RUM application in OTel-native backends
  'browser.language': navigator.language,
  'browser.user_agent': navigator.userAgent,
  'session.id': sessionId,
  'screen.width': window.screen.width,
  'screen.height': window.screen.height,
});

// ---- Tracer provider + exporter ----------------------------------------------
const provider = new WebTracerProvider({ resource });

provider.addSpanProcessor(
  new BatchSpanProcessor(
    new OTLPTraceExporter({ url: COLLECTOR_TRACES_URL }),
    { scheduledDelayMillis: 1500 } // small batch delay; keeps the demo responsive
  )
);

provider.register({
  contextManager: new ZoneContextManager(), // tracks async context across events
  propagator: new W3CTraceContextPropagator(),
});

// ---- Auto-instrumentations ---------------------------------------------------
registerInstrumentations({
  instrumentations: [
    new DocumentLoadInstrumentation(),      // page load + resource timings
    new UserInteractionInstrumentation(),   // clicks, etc.
    new FetchInstrumentation({
      // Inject traceparent into calls to the gateway so the browser span and the
      // backend trace share one trace_id. THIS is the end-to-end stitch.
      propagateTraceHeaderCorsUrls: GATEWAY_URLS,
      clearTimingResources: true,
    }),
  ],
});

const tracer = trace.getTracer(SERVICE_NAME, SERVICE_VERSION);

// ---- Core Web Vitals as OTel spans -------------------------------------------
// web-vitals reports LCP, INP, CLS, FCP, TTFB. Emit each as a short span carrying
// the metric value + rating, tagged with the session. (RUM is not yet a first-class
// OTel signal, so vitals are modeled as spans/attributes — current standard practice.)
function reportVital({ name, value, rating, id }) {
  const span = tracer.startSpan(`web-vital.${name}`);
  span.setAttribute('web_vital.name', name);
  span.setAttribute('web_vital.value', value);
  span.setAttribute('web_vital.rating', rating);  // good | needs-improvement | poor
  span.setAttribute('web_vital.id', id);
  span.setAttribute('session.id', sessionId);
  span.setAttribute('page.url', window.location.pathname);
  span.end();
}

onLCP(reportVital);
onINP(reportVital);
onCLS(reportVital);
onFCP(reportVital);
onTTFB(reportVital);

// ---- Unhandled error capture -------------------------------------------------
window.addEventListener('error', (e) => {
  const span = tracer.startSpan('browser.error');
  span.setAttribute('error.message', e.message || 'unknown');
  span.setAttribute('error.source', e.filename || 'n/a');
  span.setAttribute('session.id', sessionId);
  span.recordException && span.recordException(e.error || new Error(e.message));
  span.end();
});

window.addEventListener('unhandledrejection', (e) => {
  const span = tracer.startSpan('browser.unhandled_rejection');
  span.setAttribute('error.message', String(e.reason));
  span.setAttribute('session.id', sessionId);
  span.end();
});

// ---- Helper for app code: wrap a user action in an explicit span -------------
// Exported so index.js can create a clear "user fetches products" span that the
// fetch instrumentation nests inside, producing a clean user-action -> HTTP trace.
export function traceUserAction(name, fn) {
  const span = tracer.startSpan(name);
  span.setAttribute('session.id', sessionId);
  return context.with(trace.setSpan(context.active(), span), async () => {
    try {
      const result = await fn();
      span.setAttribute('action.outcome', 'success');
      return result;
    } catch (err) {
      span.setAttribute('action.outcome', 'error');
      span.setAttribute('error.message', String(err));
      span.recordException && span.recordException(err);
      throw err;
    } finally {
      span.end();
    }
  });
}

export { sessionId };
console.info('[otel] web instrumentation active — session', sessionId);
