// instrumentation.js
// Raw OpenTelemetry browser instrumentation for the OTel Observability Lab frontend.
// Written against the OpenTelemetry JS 2.x / 0.20x API (mid-2026).
//
// Deliberately NOT using a vendor wrapper (e.g. Grafana Faro) — keeps the pipeline
// vendor-neutral and consistent with the bare-OTel backend.
//
// Flow:  browser spans  ->  OTLP/HTTP  ->  OTel Collector  ->  Dash0 / Dynatrace
// W3C traceparent is propagated to the gateway so a user's click joins the SAME
// trace as gateway -> product-svc -> postgres -> (POLICY_DENY drop).
//
// 2.x API notes (breaking changes vs 1.x):
//   - `Resource` class removed -> use `resourceFromAttributes()`.
//   - `provider.addSpanProcessor()` removed -> pass `spanProcessors: [...]` to the
//     WebTracerProvider constructor instead.

import { WebTracerProvider } from '@opentelemetry/sdk-trace-web';
import { BatchSpanProcessor } from '@opentelemetry/sdk-trace-base';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { ZoneContextManager } from '@opentelemetry/context-zone';
import { W3CTraceContextPropagator } from '@opentelemetry/core';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { registerInstrumentations } from '@opentelemetry/instrumentation';
import { DocumentLoadInstrumentation } from '@opentelemetry/instrumentation-document-load';
import { FetchInstrumentation } from '@opentelemetry/instrumentation-fetch';
import { UserInteractionInstrumentation } from '@opentelemetry/instrumentation-user-interaction';
import { trace, context } from '@opentelemetry/api';
import { onLCP, onINP, onCLS, onFCP, onTTFB } from 'web-vitals';

// ---- Configuration -----------------------------------------------------------
const COLLECTOR_TRACES_URL =
  (typeof window !== 'undefined' && window.__OTEL_COLLECTOR_URL__) ||
  'http://localhost:4318/v1/traces';

// Gateway origin(s) that should receive the W3C traceparent header — the stitch.
const GATEWAY_URLS = [
  /localhost:8000/,
  /\.elb\.amazonaws\.com/,
];

const SERVICE_NAME = 'web-frontend';
const SERVICE_VERSION = '0.1.0';

// ---- Session + user context --------------------------------------------------
function getSessionId() {
  try {
    let id = sessionStorage.getItem('otel_session_id');
    if (!id) {
      id = (crypto.randomUUID && crypto.randomUUID()) ||
        String(Date.now()) + Math.random().toString(16).slice(2);
      sessionStorage.setItem('otel_session_id', id);
    }
    return id;
  } catch (_) {
    return String(Date.now()) + Math.random().toString(16).slice(2);
  }
}

const sessionId = getSessionId();

// 2.x: build the resource via the factory, not `new Resource()`.
const resource = resourceFromAttributes({
  'service.name': SERVICE_NAME,
  'service.version': SERVICE_VERSION,
  'telemetry.sdk.language': 'webjs',
  'browser.language': navigator.language,
  'browser.user_agent': navigator.userAgent,
  'session.id': sessionId,
  'screen.width': window.screen.width,
  'screen.height': window.screen.height,
});

// ---- Session span processor --------------------------------------------------
// Stamps session context onto EVERY span at creation time — guarantees session.id
// lands on auto-instrumentation spans (documentLoad, resourceFetch, web-vitals)
// that don't pick it up from the resource reliably.
class SessionSpanProcessor {
  onStart(span) {
    span.setAttribute('session.id', sessionId);
  }
  onEnd() {}
  shutdown() { return Promise.resolve(); }
  forceFlush() { return Promise.resolve(); }
}

// ---- Tracer provider + exporter (2.x constructor-based wiring) ---------------
const exporter = new OTLPTraceExporter({ url: COLLECTOR_TRACES_URL });

// 2.x: span processors are passed to the constructor; addSpanProcessor() is gone.
const provider = new WebTracerProvider({
  resource,
  spanProcessors: [
    new SessionSpanProcessor(),
    new BatchSpanProcessor(exporter, { scheduledDelayMillis: 2000 }),
  ],
});

provider.register({
  contextManager: new ZoneContextManager(),
  propagator: new W3CTraceContextPropagator(),
});

// ---- Auto-instrumentations ---------------------------------------------------
registerInstrumentations({
  instrumentations: [
    new DocumentLoadInstrumentation(),
    new UserInteractionInstrumentation({
      shouldPreventSpanCreation: (() => {
        let lastClick = 0;
        return (eventType, element) => {
          const now = Date.now();
          if (now - lastClick < 300) return true;  // suppress duplicates within 300ms
          lastClick = now;
          return false;  // allow the first click only
        };
      })(),
    }),
    new FetchInstrumentation({
      propagateTraceHeaderCorsUrls: GATEWAY_URLS,
      clearTimingResources: true,
      ignoreUrls: [/\/v1\/traces/, /:4318/],
    }),
  ],
});

const tracer = trace.getTracer(SERVICE_NAME, SERVICE_VERSION);

// ---- Core Web Vitals as OTel spans -------------------------------------------
function reportVital(metric) {
  try {
    const span = tracer.startSpan(`web-vital.${metric.name}`);
    span.setAttribute('web_vital.name', metric.name);
    span.setAttribute('web_vital.value', metric.value);
    span.setAttribute('web_vital.rating', metric.rating);
    span.setAttribute('web_vital.id', metric.id);
    span.setAttribute('session.id', sessionId);
    span.setAttribute('page.url', window.location.pathname);
    span.end();
  } catch (_) { /* never let telemetry break the page */ }
}

onLCP(reportVital);
onINP(reportVital);
onCLS(reportVital);
onFCP(reportVital);
onTTFB(reportVital);

// ---- Unhandled error capture -------------------------------------------------
window.addEventListener('error', (e) => {
  try {
    const span = tracer.startSpan('browser.error');
    span.setAttribute('error.message', e.message || 'unknown');
    span.setAttribute('error.source', e.filename || 'n/a');
    span.setAttribute('session.id', sessionId);
    if (span.recordException && e.error) span.recordException(e.error);
    span.end();
  } catch (_) {}
});

window.addEventListener('unhandledrejection', (e) => {
  try {
    const span = tracer.startSpan('browser.unhandled_rejection');
    span.setAttribute('error.message', String(e.reason));
    span.setAttribute('session.id', sessionId);
    span.end();
  } catch (_) {}
});

// ---- Helper: wrap a user action in an explicit span --------------------------
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
      if (span.recordException) span.recordException(err);
      throw err;
    } finally {
      span.end();
    }
  });
}

export { sessionId };
console.info('[otel] web instrumentation active — session', sessionId);
