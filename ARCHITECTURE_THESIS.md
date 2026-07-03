# Observability Architecture & Thesis — OTel Lab vs. Vendor (Dynatrace)

**Author framing (from LinkedIn):** *"I specialize in making the haystack observable — so the
needle never stays hidden. Full-spectrum visibility: flow data to understand the enterprise-wide
haystack, and packet-level analytics to pinpoint the needle — the ground truth that defines SLA
integrity."* This document extends that philosophy from Network/APM into **Network + APM + LLM
observability, converged through OpenTelemetry**, with a deliberate open-vs-vendor comparison.

---

## 1. The core thesis — supplement the vendor, don't replace it

**The enterprise reality:** customers can't build observability ground-up. They must adopt a
reputable vendor (Dynatrace, Datadog, Splunk, New Relic) for maturity, support, and speed. **But
adopting a vendor should not cap what they can see.** Whatever the vendor's native tooling can't
reach, the OpenTelemetry Collector bridges — turning OTel from an *alternative* to the vendor into
the customer's **insurance policy against vendor limits.**

This is a complementary posture, not adversarial:
- **Vendor (e.g. Dynatrace OneAgent + OpenLLMetry):** best-in-class auto-instrumentation where it's
  strong — full-stack app/host/process, Davis AI, mature UI.
- **Open pipeline (OTel Collector → Dash0 / O2):** everything else — eBPF/network signals, logs the
  vendor won't license, metric types the vendor can't ingest, custom AIOps, and portability.
- **The seam is the Collector.** It feeds the vendor its native way AND carries the full-spectrum
  signal set to an open backend. No lock-in, no blind spots.

**Why this wins in enterprise:** almost no mature shop is purely one or the other. They run vendor
agents where strong AND OTel pipelines to fill gaps and preserve optionality. This design *is* that
pragmatic hybrid — the architect's answer, not the purist's.

---

## 2. Collect ≠ Store — the governance model (the haystack/needle spine)

"Collect everything OTel" is **not** naive maximalism. It is **full-spectrum *collectability*,
governed at the Collector by purpose and demand.** This directly maps the flow-vs-packet philosophy:

| Layer | Analogy | Posture | Collector role |
|---|---|---|---|
| **Flow data** | the haystack | broad, always-on, enterprise-wide visibility | collect wide, sample/aggregate |
| **Packet-level** | the needle | deep, on-demand, SLA ground truth | capture deep when demand/anomaly spikes |

The Collector is the **governance layer**, not just a pipe. It decides:
- what's collected **wide** (always-on, low cardinality) vs.
- stored **deep** (high fidelity, selective) vs.
- **escalated** to full capture (on anomaly, on demand).

**Why this matters (learned first-hand):** observability is not free — a 20-minute test at low
request rate generated ~4M metric data points. "Collect everything" without governance is exactly
what blows up an observability bill. So the discipline is: **collect the full spectrum for
*collectability*, then apply cardinality reduction and retention tiers at the Collector as a
deliberate cost lever.** That is the difference between a hobby pipeline and an enterprise platform —
and it is the OTel-era continuation of maturing "siloed tooling into a unified platform" (JPMC).

**Future direction (parked): "lake of lakes / mother lake"** — a federated store-of-stores so the
governance model spans multiple backends/lakes, routing signals by purpose to the right tier. Noted
for later; not in current scope.

---

## 3. The parallel-pipeline design (open vs. vendor, side by side)

Two independent pipelines observing the **same workload**, so the comparison is honest:

```
                         ┌─────────────── OTel Collector (governance seam) ───────────────┐
  app + eBPF signals ───►│  receivers: OTLP, hostmetrics, Hubble(prom), Beyla/OBI          │
  (Cilium/Hubble,        │  processors: memory_limiter, resource, batch, [cardinality]     │
   Beyla/OBI, SDK)       │  exporters:  ── Dash0 (everything)                              │
                         │              ── Dynatrace (surgical: only the gaps)             │
                         └────────────────────────────────────────────────────────────────┘
        │                                            ▲
        ▼                                            │ (bridge gaps only)
  Dynatrace OneAgent + OpenLLMetry ──────────────────┘
  (vendor-native: full-stack app/host/process, LLM KPIs, Davis AI)
```

- **Dash0 (open path):** the full spectrum — traces, logs, all metrics including eBPF/network.
- **Dynatrace (vendor path):** OneAgent + OpenLLMetry native best, **plus** the Collector bridging
  only what the vendor can't natively capture.

> **Clean-comparison note:** for a pristine parallel, the Collector→Dynatrace export should be
> *surgical* — feed DT only the gaps (eBPF, logs), not a full duplicate of what OneAgent already
> captures. Otherwise DT is double-fed and "vendor-native vs. open" blurs. (Current lab exports
> broadly to both; tighten to surgical in the capstone.)

---

## 4. What the Collector bridges — the FOUR concrete gaps

"Bridge the gap" is specific, not vague. From what the vendor natively cannot do (observed
first-hand in this lab):

1. **eBPF / network telemetry** — Cilium/Hubble POLICY_DENY drops, Beyla/OBI TCP failed connections,
   flow bytes. OneAgent does not capture the L3/L4 eBPF layer. **This is the network-blindspot
   signature** — the whole reason the lab exists.
2. **Metric types the vendor rejects** — observed live: Dynatrace's OTLP endpoint dropped
   `beyla.network.flow.bytes`, `dns.lookup.duration`, `http.server.request.duration`
   (`UNSUPPORTED_METRIC_TYPE_*` — cumulative histograms / monotonic sums). Dash0 accepts them.
3. **Logs (licensing)** — the DT trial has no log-ingest license (HTTP 402). The open pipeline
   carries logs to Dash0. A licensing gap, bridged by routing.
4. **Custom AIOps RCA** — the gated `/diagnose` (Bedrock Nova Micro) correlating network + app
   signals into a root cause. Neither OneAgent nor OpenLLMetry does cross-domain network+app RCA.

---

## 5. LLM observability — raw OTel vs. OpenLLMetry (the vendor's recommendation)

**Dynatrace's recommended LLM path = OpenLLMetry** (Traceloop SDK): install the SDK, initialize the
tracer, point `TRACELOOP_BASE_URL` at DT's OTLP endpoint with an ingest token. It auto-extracts LLM
KPIs (model, tokens, temperature, prompt/completion) from frameworks (OpenAI, Bedrock, LangChain).
DT recommends it because **OneAgent can't auto-instrument Python LLM calls well**, and plain OTel
auto-instrumentation "falls short in capturing model name, version, prompt/completion tokens."

**This lab's choice = raw OTel GenAI semantic conventions** — set `gen_ai.*` attributes explicitly:
`gen_ai.operation.name`, `gen_ai.provider.name` (aws.bedrock), `gen_ai.request.model`,
`gen_ai.usage.input_tokens` / `output_tokens`, `gen_ai.response.model`,
`gen_ai.response.finish_reasons`, plus namespaced custom `otel_lab.gen_ai.cost_usd` (no standard
cost attribute exists). Prompt/completion bodies via opt-in `gen_ai.input.messages` /
`gen_ai.output.messages` (default OFF — PII risk; redact at Collector in production).

**The honest framing:** OpenLLMetry is a fine, Apache-2.0 SDK that *outputs standard OTel gen_ai
data* — not proprietary lock-in. But it is still a wrapper SDK. This lab uses the primitives
directly for the same reason it rejects Grafana Faro on the browser: no wrapper dependency, full
control over what's captured, and it proves understanding of the convention rather than delegating
to an SDK. **Both emit the same standard `gen_ai.*` data — OpenLLMetry automates what the lab does
by hand.** (Note: DT's full OpenLLMetry AI-observability experience wants a DPS/Grail license tier
the trial may lack — another reason the raw gen_ai spans via the Collector are the pragmatic path.)

---

## 6. Dynatrace — strengths & weaknesses (interview study guide)

Grounded in what was *actually observed* running DT in this lab — more convincing than textbook.

### Strengths (where DT / OneAgent shines)
- **OneAgent auto-instrumentation** — drop it on a host, get full-stack app/process/host visibility
  with near-zero code. Java/.NET/Go/Node especially. Genuinely fast time-to-value.
- **Smartscape / topology** — automatic dependency mapping (gateway → product-svc), continuously
  updated. Strong for understanding blast radius.
- **Davis AI** — automatic problem detection and root-cause correlation, no query-writing.
- **Unified full-stack context** — infra + process + service + real-user, one model, one UI.
- **Native OTLP ingest** — accepts open OTel data too, so it plays in a hybrid pipeline.

### Weaknesses / limits (observed first-hand)
- **eBPF / network layer** — OneAgent does not capture Cilium/Hubble POLICY_DENY, TCP retransmits,
  flow-level detail. The network blindspot lives here. (Collector bridges.)
- **OTLP metric-type support** — rejects cumulative-histogram / monotonic-sum types
  (`beyla.network.flow.bytes`, `dns.lookup.duration`, `http.server.request.duration`). Not every
  OTel metric lands. (Dash0 accepts them.)
- **Licensing gates capability** — logs need a log license (trial = HTTP 402); full LLM/AI
  observability wants DPS/Grail tiers. Capability is entitlement-bound, not just technical.
- **Python LLM auto-instrumentation** — OneAgent can't; requires OpenLLMetry SDK. A real gap DT
  itself documents.
- **Token/credential operational overhead** — API + data-ingest tokens expire; stale tokens silently
  break image pulls (401) and OTLP ingest (401). Operationally, DT has real token lifecycle to manage
  (learned the hard way: rotate operator token → fix ImagePullBackOff; rotate ingest token → restore
  OTLP traces).
- **UI can mask data** — the "Add traces" onboarding card hid live traces; data was in **Explorer**.
  A UX rough edge worth knowing.

### Talking points that show depth (for the SME / interviewer)
- "DT is excellent at *auto* full-stack, but the eBPF/network layer and cross-domain network+app RCA
  are where an open pipeline complements it."
- "DT's OTLP endpoint is opinionated about metric types — I saw it reject cumulative histograms my
  open backend accepts. That's a real portability nuance in OTLP metric support across backends."
- "Its AI story routes through OpenLLMetry because OneAgent can't do Python LLM — same standard
  gen_ai data I emit directly."
- "Operationally, token lifecycle matters — expired tokens took down image pulls and ingest; worth
  automating rotation."

---

## 7. Roadmap (parked items, for the capstone)

- **Surgical Collector→DT bridge** — feed DT only the gaps, for a pristine parallel.
- **OpenLLMetry into DT** — implement the vendor's recommended LLM path for a true side-by-side vs.
  the raw-OTel gen_ai spans.
- **In/out message capture** — `gen_ai.input/output.messages` with Collector-side redaction.
- **O2 / OpenObserve as third backend** — note AGPL-3.0 (copyleft) vs. Apache; a conscious license
  choice for anyone productionizing.
- **EUM/RUM browser layer** — already built, parked (separate handoff doc).
- **"Lake of lakes / mother lake"** — federated store-of-stores; governance spanning multiple lakes.
- **Cardinality governance at the Collector** — the collect-vs-store lever, made explicit.

---

## 8. One-paragraph thesis (for saying it out loud)

"My open observability lab collects the full spectrum through OpenTelemetry — network via eBPF, app
via the SDK, LLM via gen_ai conventions — and governs it at the Collector, because collecting
everything and *storing* everything are different decisions driven by purpose and demand: flow data
for the enterprise-wide haystack, packet-level depth for the SLA needle. Enterprises can't build this
ground-up, so they adopt a reputable vendor like Dynatrace — OneAgent and OpenLLMetry at their best.
But they shouldn't be capped by what the vendor natively sees. My Collector feeds the vendor its
native way AND bridges the gaps the vendor can't reach — eBPF/network signals, metric types it
rejects, logs it won't license, and cross-domain AIOps RCA — while keeping everything portable to an
open backend. The vendor gives maturity; the open pipeline guarantees no blind spots and no lock-in."
