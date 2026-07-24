# Regress

**Your agent's production failures become its regression suite. Automatically.**

Regress is an open-source **failure-to-eval compiler**. It closes the loop that
every LLM observability vendor admits is open:

```
production trace → clustered failure → tracked issue → auto-generated eval → CI regression gate
```

...as a single self-hostable tool you can adopt in under 5 minutes.

> **Status: pre-alpha (Phase 2).** The architecture below is the target shape.
> Today `regress up` serves a health check and a real OTLP/HTTP ingest
> endpoint (`POST /v1/traces`, protobuf or JSON) that parses GenAI semantic
> convention spans into SQLite. `regress traces` lists what's been ingested.
> `from regress import instrument` patches the `openai` and `anthropic`
> clients to emit those spans automatically, `@task` groups a function's
> calls into one trace, and `feedback()` attaches a score to a trace after
> the fact. See [MASTER_PLAN](#roadmap) for what's built vs. planned.

## Quickstart

```bash
pip install regress-ai
regress up          # starts collector + API + dashboard, one process, SQLite by default
```

```python
# their app — one line changed
from regress import instrument
instrument()        # patches OpenAI/Anthropic SDKs + emits OTel GenAI spans to localhost
```

Then use your app, open `http://localhost:8990`, see traces, click "generate
evals" on a failure cluster, and get a ready-to-commit `evals/` directory plus
a GitHub Action.

No Postgres required to start. No API key for Regress itself. No account. No
YAML until you want it.

## Architecture

```
                        ┌────────────────────────────────────────────────┐
                        │                 regress up (FastAPI)           │
                        │                                                │
 user's app ──OTLP──▶   │  /v1/traces  ──▶  Ingest ──▶ Store (SQLite/PG) │
 (instrument() or       │                              + embeddings      │
  any OTel exporter)    │                                                │
                        │  Scorer  ── deterministic checks + judge ──▶   │
                        │            span/trace scores                   │
                        │                                                │
                        │  Clusterer ── embed failed traces ──▶ Issues   │
                        │               (HDBSCAN over failure vectors,   │
                        │                LLM-written issue titles)       │
                        │                                                │
                        │  EvalGen ── issue ──▶ evals/<issue>.yaml       │
                        │             deterministic where possible,      │
                        │             judge-based where not              │
                        │                                                │
                        │  Calibrator ── human labels ──▶ judge kappa,   │
                        │                threshold tuning, report        │
                        │                                                │
                        │  Dashboard (React+TS+Tailwind, served static)  │
                        └────────────────────────────────────────────────┘

 CI: regress run evals/ --against <traces|live app> ──▶ pass/fail + significance test
     shipped as a reusable GitHub Action (regress-ai/gate-action)
```

## Why not just Langfuse / Braintrust / \<observability vendor\>?

Those tools are excellent at the first half of the loop: capturing traces and
scoring them. What they leave to you, manually, every time, is the second
half — turning a cluster of bad traces into a committed regression test that
blocks a bad deploy. Regress's only job is that second half, done
automatically, and it speaks OpenTelemetry GenAI conventions so it plugs into
whatever you're already exporting from. It is not trying to replace your
observability stack; it's trying to make one specific workflow (failure →
eval → gate) something you never do by hand again.

## Design principles

- **Zero-config default path.** SQLite + local embeddings (`bge-small-en-v1.5`)
  out of the box. Postgres + pgvector is opt-in via `REGRESS_DB_URL` for scale.
- **Standards over SDK lock-in.** Ingestion speaks OpenTelemetry GenAI
  semantic conventions over OTLP/HTTP. `instrument()` is a convenience, not a
  requirement.
- **Everything is also a file.** Generated evals are plain, readable YAML +
  Python in your repo, runnable with `regress run evals/` or plain pytest —
  no server required in CI.
- **One process, one port** for local dev; Docker Compose for the full stack.

## Roadmap

Tracking against the MASTER_PLAN in `CLAUDE.md`:

- [x] **Phase 0 — Skeleton.** Repo, pyproject, CLI stub, CI, license, README.
- [x] **Phase 1 — Ingest + Store.** OTLP endpoint, GenAI-convention parsing, SQLite storage.
- [x] **Phase 2 — `instrument()` SDK.** Patch openai + anthropic, `@task`, `feedback()`.
- [ ] **Phase 3 — Scorer.** Deterministic checks + LLM-judge with stored rubrics.
- [ ] **Phase 4 — Clusterer + Issues.** Embeddings, HDBSCAN, lifecycle states.
- [ ] **Phase 5 — EvalGen + CI gate.** YAML evals, `regress run`, GitHub Action. (v0.1.0)
- [ ] **Phase 6 — Calibrator.** Labeling flow, judge-vs-human kappa report.
- [ ] **Phase 7 — Dashboard.** Trace explorer, issue kanban, calibration view. (v0.2.0)
- [ ] **Phase 8 — Dogfood + case study.** Real numbers in `docs/case-study.md`.

## Non-goals (v0)

No hosted/multi-tenant SaaS, no auth beyond a single optional bearer token, no
prompt-management/playground features, no fine-tuning loops, no support for
non-GenAI OTel traffic, no Kubernetes manifests. This scope is intentional.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

To try ingestion today, point any OTLP/HTTP exporter at `regress up`'s
`/v1/traces` endpoint (protobuf or JSON, following the [OpenTelemetry GenAI
semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai)),
then list what came in:

```bash
regress up &
curl -X POST http://localhost:8990/v1/traces \
  -H "Content-Type: application/x-protobuf" --data-binary @trace.pb
regress traces
```

Or use `instrument()` so your existing `openai`/`anthropic` calls export
automatically — no manual OTLP payloads required:

```python
from regress import instrument, task, feedback

instrument()  # patches openai + anthropic clients in this process

@task(name="answer_question")
def answer(question: str) -> str:
    response = client.chat.completions.create(model="gpt-4o-mini", messages=[...])
    return response.choices[0].message.content

# later, e.g. from a user thumbs-down in your app
feedback(trace_id=trace_id, score=0.0, comment="wrong refund policy")
```

See [examples/quickstart.py](examples/quickstart.py) for a runnable version.

## License

Apache-2.0. See [LICENSE](LICENSE).
