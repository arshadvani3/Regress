# regress-ai 0.1.0 — first public release

**Your agent's production failures become its regression suite. Automatically.**

Regress is an open-source **failure-to-eval compiler**: it closes the loop every
LLM observability tool leaves open —
`production trace → clustered failure → tracked issue → auto-generated eval → CI regression gate`
— as a single self-hostable tool you can adopt in under 5 minutes.

```bash
pip install regress-ai
regress demo        # load a sample scenario — see the whole loop, zero setup
regress up          # open http://localhost:8990
```

## Does it actually work?

Run end-to-end against a real LlamaIndex RAG over SQuAD, numbers straight from
the run:

- **200 traces** ingested from 100 questions with a one-line `instrument()`
- **21 real failures** found (79% answer accuracy) → **2 auto-titled issues**
- → **8 committed regression cases**, judge-vs-human **Cohen's κ = 0.435**
- Gate **caught a degraded RAG (79% → 47%) at p < 0.00001**, ignored a 4-pt
  noise drop — total API cost under **$0.05**

Full write-up: [docs/case-study.md](docs/case-study.md).

## What's in 0.1.0

The complete loop, one command per stage:

- **Ingest** — `instrument()` patches OpenAI/Anthropic (streaming completions
  included) and emits OpenTelemetry GenAI spans; or point any OTLP exporter at
  `regress up`. SQLite by default, no account, no API key for Regress itself.
- **Score** — deterministic checks + rubric-based LLM-judge; the judge sees the
  user input, not just the output. `regress init` scaffolds a starter config.
- **Cluster** — HDBSCAN over failure embeddings into tracked Issues with
  LLM-written titles and an `active → resolved → regressed` lifecycle.
- **EvalGen** — each issue becomes a sanitized, human-editable YAML eval plus a
  pytest module (`pytest evals/` runs with no server).
- **Gate** — replay or hit a live app and block CI on a *statistically
  significant* regression (two-proportion test), shipped as a reusable GitHub
  Action.
- **Calibrate** — hand-label a sample and get Cohen's κ, because the judge
  drives everything above.
- **Dashboard** — trace explorer, issue kanban, and calibration report, served
  static from the one `regress up` process.

**Try it with zero setup:** `regress demo` seeds failing traces already scored
and clustered (including a `regressed` issue) so the dashboard is populated the
moment you install.

**Deploying beyond localhost:** optional bearer-token auth
(`REGRESS_AUTH_TOKEN`) and PII-redaction-at-ingest (`REGRESS_SANITIZE_INGEST`),
both off by default; file-backed SQLite runs in WAL mode automatically. See
[docs/usage.md](docs/usage.md#deploying-beyond-localhost).

## Status

**Pre-alpha.** The full loop works end to end and is proven on a real RAG, but
it's a self-hosted single-node tool and public APIs may still shift. Next up:
async + cached judge calls, and Postgres + pgvector for teams past the SQLite
default.

## Install

```bash
pip install regress-ai
pip install 'regress-ai[cluster]'   # add clustering (sentence-transformers)
```

Apache-2.0.
