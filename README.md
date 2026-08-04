<div align="center">

# Regress

**Your agent's production failures become its regression suite. Automatically.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![CI](https://github.com/arshadvani3/Regress/actions/workflows/ci.yml/badge.svg)](https://github.com/arshadvani3/Regress/actions/workflows/ci.yml)
[![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange.svg)](#status--whats-next)

</div>

Regress is an open-source **failure-to-eval compiler**. Every LLM observability
vendor captures traces and scores them — then leaves the hard part to you, by
hand, forever: turning a cluster of bad outputs into a committed regression test
that blocks the next bad deploy. Regress automates exactly that loop:

```
production trace → clustered failure → tracked issue → auto-generated eval → CI regression gate
```

Self-hostable, adoptable in under 5 minutes, SQLite by default, no account and
no API key for Regress itself.

<!-- TODO: replace with a real demo GIF — see docs/assets/ -->
<!-- ![Regress demo](docs/assets/demo.gif) -->

---

## Does it actually work?

Yes — here's the whole loop run end to end against a real
[LlamaIndex](https://github.com/run-llama/llama_index) RAG over
[SQuAD](https://rajpurkar.github.io/SQuAD-explorer/), with numbers straight out
of the run:

| Stage | Result |
|---|---|
| **Ingest** (one line: `instrument()`) | 100 questions → **200 traces**, zero app changes |
| **Score** vs. gold answers | **21 real failures** found (79% answer accuracy) |
| **Cluster** | 21 failures → **2 auto-titled issues** |
| **EvalGen** | → **8 committed regression cases** |
| **Calibrate** | judge-vs-human **Cohen's κ = 0.435** |
| **Gate** | caught a degraded RAG (79% → 47%) at **p < 0.00001**, ignored a 4-pt noise drop |

Total API cost for the entire study: **under $0.05**. It even found (and fixed)
a real bug in Regress itself. Full write-up → **[docs/case-study.md](docs/case-study.md)**.

---

## Quickstart

```bash
pip install regress-ai
# bleeding edge: pip install git+https://github.com/arshadvani3/Regress.git

regress demo        # load a sample scenario — see the whole loop, zero setup
regress up          # then open http://localhost:8990
```

`regress demo` seeds a small sample (failing traces already scored and
clustered into Issues, including a `regressed` one) so the dashboard is
populated the moment you install — nothing to instrument first. `regress demo
--reset` clears it. To point Regress at **your** app instead, change one line:

```python
from regress import instrument
instrument()        # patches OpenAI/Anthropic SDKs, emits OTel spans to localhost
```

Then use your app, open **http://localhost:8990**, watch traces stream in, and
run the loop below. No Postgres, no account, no YAML until you want it.

<!-- TODO: replace with a real dashboard screenshot — see docs/assets/ -->
<!-- ![Dashboard](docs/assets/dashboard.png) -->

---

## How it works

```
                        ┌────────────────────────────────────────────────┐
                        │                 regress up (FastAPI)           │
                        │                                                │
 your app ──OTLP──▶     │  /v1/traces  ──▶  Ingest ──▶ Store (SQLite/PG) │
 (instrument() or       │                              + embeddings      │
  any OTel exporter)    │                                                │
                        │  Scorer  ── deterministic checks + judge ──▶   │
                        │            span/trace scores                   │
                        │                                                │
                        │  Clusterer ── embed failed traces ──▶ Issues   │
                        │               (HDBSCAN, LLM-written titles,    │
                        │                active → resolved → regressed)  │
                        │                                                │
                        │  EvalGen ── issue ──▶ evals/<issue>.yaml       │
                        │                                                │
                        │  Calibrator ── human labels ──▶ judge kappa    │
                        │                                                │
                        │  Dashboard (React+TS+Tailwind, served static)  │
                        └────────────────────────────────────────────────┘

 CI: regress run evals/ --against <live app> ──▶ pass/fail + significance test
     shipped as a reusable GitHub Action (.github/actions/gate)
```

Six stages, one command each:

| Stage | Command | What it does |
|---|---|---|
| Ingest | `instrument()` / any OTLP exporter | Record LLM calls as traces |
| Score | `regress score` | Deterministic checks + LLM-judge |
| Cluster | `regress cluster` | Group failures into tracked Issues |
| EvalGen | `regress evalgen` | Issue → YAML + pytest regression test |
| Gate | `regress run --gate` | Fail CI on a *significant* regression |
| Calibrate | `regress calibrate` | Measure how much to trust the judge |

→ **[Full walkthrough with the reasoning behind each stage](docs/how-it-works.md)** (plus an interactive visual version).

---

## Usage

A tour of the loop. Full flag-by-flag reference: **[docs/usage.md](docs/usage.md)**.

**Ingest** — one line in your app, or point any OTel exporter at `regress up`:

```python
from regress import instrument
instrument()   # every openai/anthropic call now exports a trace
```

**Score** — deterministic checks + an optional LLM-judge, configured in an
optional `regress.yaml` (`regress init` scaffolds one with a menu of
ready-to-use rubrics):

```bash
regress init                       # writes a starter regress.yaml
regress score --config regress.yaml
```

**Cluster** scored-bad traces into Issues (needs the `cluster` extra). A new
failure landing in a *resolved* issue flips it to **regressed** — a fix that
didn't hold:

```bash
pip install 'regress-ai[cluster]'
regress cluster
```

**Generate evals** — each issue becomes a sanitized, human-editable YAML eval
plus a pytest module (`pytest evals/` works with no server):

```bash
regress evalgen
```

> Or run score → cluster → evalgen in one shot: `regress analyze`.

**Gate CI** — replay recorded traces, or hit your live app and block the deploy
on a statistically significant drop (a two-proportion test, not a raw diff):

```bash
regress run evals/ --against http://localhost:8000/predict --gate
```

**Calibrate the judge** — hand-label a sample and get Cohen's κ, because the
judge drives everything above:

```bash
regress calibrate --label 20 --labeler you@example.com
regress calibrate --report
```

---

## Why not just Langfuse / Braintrust / \<observability vendor\>?

Those tools are excellent at the *first* half of the loop — capturing traces
and scoring them. What they leave to you, manually, every time, is the *second*
half: turning a cluster of bad traces into a committed regression test that
blocks a bad deploy. Regress's only job is that second half, done
automatically, and it speaks OpenTelemetry GenAI conventions so it plugs into
whatever you're already exporting from. It's not replacing your observability
stack — it's making one specific workflow (failure → eval → gate) something you
never do by hand again.

## Design principles

- **Zero-config default path.** SQLite + local embeddings (`bge-small-en-v1.5`)
  out of the box. Postgres + pgvector is opt-in via `REGRESS_DB_URL` for scale.
- **Standards over SDK lock-in.** Ingestion speaks OpenTelemetry GenAI
  conventions over OTLP/HTTP. `instrument()` is a convenience, not a requirement.
- **Everything is also a file.** Generated evals are plain YAML + Python in your
  repo, runnable with `regress run` or plain `pytest` — no server in CI.
- **One process, one port** for local dev; the judge works against any
  OpenAI-compatible endpoint, including a fully-local Ollama.

## Non-goals (v0)

No hosted/multi-tenant SaaS, no auth beyond a single optional bearer token, no
prompt-management/playground features, no fine-tuning loops, no non-GenAI OTel
traffic, no Kubernetes manifests. The scope is intentional.

## Status & what's next

**Pre-alpha.** The full loop — ingest → score → cluster → evalgen → gate →
calibrate, plus the dashboard — works end to end, proven against a real
LlamaIndex RAG (see the [case study](docs/case-study.md)). It's a self-hosted
single-node tool today; public APIs may still shift.

Streaming-completion capture already landed (`instrument()` traces
token-streamed responses without forcing non-streaming), and a shared
deployment can now require a bearer token (`REGRESS_AUTH_TOKEN`) and redact
PII before it's stored (`REGRESS_SANITIZE_INGEST`) — see
[docs/usage.md](docs/usage.md#deploying-beyond-localhost). Where it goes next:

- **Postgres + pgvector** for teams past the single-node SQLite default —
  the storage layer is already abstracted behind `REGRESS_DB_URL`.
- **Async, cached judge calls** so a large score run isn't a sequential wait
  and identical output+rubric pairs aren't re-judged.
- **More judge backends** beyond OpenAI-compatible — the judge is a thin
  provider-agnostic client, so Anthropic/Bedrock/local slot in cleanly.

## Contributing

```bash
git clone https://github.com/arshadvani3/Regress.git && cd Regress
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest && ruff check . && mypy src
```

The dashboard (`dashboard/`, Vite + React + TypeScript + Tailwind) is a separate
npm project that builds into `src/regress/dashboard_dist/`, which `regress up`
serves as static files:

```bash
cd dashboard && npm install
npm run dev      # Vite dev server on :5173, proxies /api to :8990
npm run build    # writes the bundle regress up serves
```

## License

Apache-2.0. See [LICENSE](LICENSE).
