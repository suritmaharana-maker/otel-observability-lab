// index.js — application logic for the OTel Lab console.
// Imports the instrumentation FIRST so all fetches are auto-traced and traceparent
// is propagated to the gateway.
import { traceUserAction, sessionId } from './instrumentation.js';

const GATEWAY = window.__GATEWAY_URL__ || 'http://localhost:8000';

const el = (id) => document.getElementById(id);
el('sid').textContent = sessionId.slice(0, 8);

function log(msg, cls = '') {
  const row = document.createElement('div');
  row.className = 'row';
  const t = new Date().toLocaleTimeString('en-GB');
  row.innerHTML = `<span class="t">${t}</span><span class="m ${cls}">${msg}</span>`;
  const box = el('log');
  box.appendChild(row);
  box.scrollTop = box.scrollHeight;
}

function setLast(status, detail, latency, statusClass) {
  el('last-status').textContent = status;
  el('last-status').className = `val ${statusClass}`;
  el('last-detail').textContent = detail;
  el('last-latency').textContent = latency != null ? `${latency} ms` : '—';
  el('last-latency').className = 'val ' +
    (latency == null ? '' : latency > 4000 ? 'err' : latency > 1000 ? 'warn' : 'ok');
}

// Core call: wrapped in a user-action span. The FetchInstrumentation creates the
// child HTTP span and injects traceparent into the gateway request.
async function callGateway(path, label) {
  const buttons = document.querySelectorAll('button');
  buttons.forEach((b) => (b.disabled = true));
  const started = performance.now();
  log(`→ <b>${label}</b> requested`, '');

  try {
    await traceUserAction(`user.${label}`, async () => {
      const res = await fetch(`${GATEWAY}${path}`, {
        headers: { 'accept': 'application/json' },
      });
      const ms = Math.round(performance.now() - started);
      if (res.ok) {
        log(`✓ ${label} <b>${res.status}</b> in ${ms} ms`, 'ok');
        setLast(`${res.status} OK`, `${label} succeeded`, ms, 'ok');
      } else {
        log(`✗ ${label} <b>${res.status}</b> in ${ms} ms`, 'err');
        setLast(`${res.status}`, `${label} returned an error`, ms, 'err');
      }
      return res;
    });
  } catch (err) {
    const ms = Math.round(performance.now() - started);
    // This is the network-policy-fault path: the request never completes / times out.
    log(`✗ ${label} <b>failed</b> after ${ms} ms — request did not complete`, 'err');
    log(`  (from the user's side this is a hung page — the network layer holds the cause)`, 'warn');
    setLast('FAILED', `${label} did not complete — likely network block`, ms, 'err');
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}

el('btn-products').addEventListener('click', () => callGateway('/products', 'products'));
el('btn-recs').addEventListener('click', () => callGateway('/recommendations', 'recommendations'));

// Steady-load loop: mirrors the backend Send-Traffic cadence (1 req / 3s).
// Lets you generate a clean RUM signal stream while you watch the fault inject.
el('btn-loop').addEventListener('click', async () => {
  log('▶ steady load: 10 requests, 1 every 3s', 'warn');
  for (let i = 1; i <= 10; i++) {
    await callGateway('/products', `products[${i}/10]`);
    if (i < 10) await new Promise((r) => setTimeout(r, 3000));
  }
  log('■ steady load complete', 'warn');
});

// Surface web vitals into the panel as they arrive (the instrumentation also
// emits them as spans). We listen to the same events here for the live display.
import('web-vitals').then(({ onLCP, onINP, onCLS }) => {
  const vitals = {};
  const render = () => {
    const parts = Object.entries(vitals).map(([k, v]) => `${k} ${v}`);
    if (parts.length) el('last-vitals').textContent = parts.join(' · ');
  };
  onLCP((m) => { vitals.LCP = Math.round(m.value) + 'ms'; render(); });
  onCLS((m) => { vitals.CLS = m.value.toFixed(3); render(); });
  onINP((m) => { vitals.INP = Math.round(m.value) + 'ms'; render(); });
}).catch(() => {});

log('instrumentation active — spans export to the collector', '');
