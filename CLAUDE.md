# CLAUDE.md — Regress

> Working name: **Regress** (CLI: `regress`). Rename is a find-and-replace away; don't block on it.

## What this is

Regress is an open-source **failure-to-eval compiler**: it closes the loop that every LLM observability vendor admits is open — `production trace → clustered failure → tracked issue → auto-generated eval → CI regression gate` — as a single self-hostable tool a developer can adopt in under 5 minutes.

One-liner for the README: **"Your agent's production failures become its regression suite. Automatically."**

## Who is building this

Arsh Advani (github.com/arshadvani3). Solo project, portfolio flagship #4 alongside AgentMesh, ARGUS, and AgentProbe. Every commit must follow the `checkpoint-commits` skill: authored solely by Arsh Advani (`arshadvani3@gmail.com`), conventional commit messages, one commit per logical unit, **never any Claude/Anthropic co-author trailer**. Run the skill's `verify_authorship.sh` at session start and before every push.

## Design north star: instant developer pickup

Every architectural decision is subordinate to this. A developer with an existing LLM app must get value in three steps:

```bash
pip install regress-ai
regress up          # starts collector + API + dashboard, one process, SQLite by default
```

```python
# their app — one line changed
from regress import instrument
instrument()        # patches OpenAI/Anthropic SDKs + emits OTel GenAI spans to localhost
```

Then they use their app, open `http://localhost:8990`, see traces, click "generate evals" on a failure cluster, and get a ready-to-commit `evals/` directory plus a GitHub Action. No Postgres required to start, no API key for Regress itself, no account, no YAML until they want it.

Hard DX rules:
- **Zero-config default path.** SQLite + local embedding model (`bge-small-en-v1.5` via sentence-transformers) out of the box. Postgres + pgvector is an opt-in `REGRESS_DB_URL` for scale.
- **Standards over SDK lock-in.** Ingestion speaks the **OpenTelemetry GenAI semantic conventions** over OTLP/HTTP. `instrument()` is a convenience, not a requirement — anyone already using Langfuse/LangSmith/OTel exporters can point their exporter at Regress and it works. This is the moat: framework-agnostic by construction.
- **Everything is also a file.** Generated evals are plain, readable YAML + Python in the user's repo, runnable with `regress run evals/` or plain pytest — no server needed in CI. The tool must never hold the user's test suite hostage.
- **One process, one port** for local dev (`regress up`), Docker Compose for the full stack. Same philosophy as AgentMesh's single-process `agentmesh up` pivot — that lesson applies here from day one.

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

### Components, in build order

1. **Ingest + Store.** FastAPI OTLP/HTTP endpoint accepting GenAI-convention spans (`gen_ai.system`, `gen_ai.request.model`, prompt/completion events, tool-call spans). Normalize into `traces / spans / messages` tables. SQLAlchemy with SQLite and Postgres backends; embeddings in a `vectors` table (pgvector when PG, sqlite-vec locally).
2. **`instrument()` SDK.** Thin wrapper: monkey-patch `openai` and `anthropic` clients, emit conventional spans, batch-export OTLP to localhost. Also a `@task` decorator for user-defined spans and a `feedback(trace_id, score, comment)` API. Keep it under ~500 LOC; it is a convenience layer, not the product.
3. **Scorer.** Two tiers, explicit in code and docs because "when deterministic vs judge" is a design statement:
   - Deterministic: JSON-schema validity, regex/exact-match assertions, tool-call argument validation, latency/cost thresholds, refusal detection.
   - Judge: rubric-based LLM-as-judge (default model configurable; cheap tier like Haiku/Groq Llama for cost). Every judge verdict stores the rubric, model, and raw reasoning for auditability.
4. **Clusterer → Issues.** Embed (failure reason + last user msg + output) for scored-bad traces; HDBSCAN into clusters; LLM writes a title + description per cluster. Issues have lifecycle: `active → resolved → regressed` (regressed = a new failing trace lands in a resolved cluster — this state transition is the headline feature, make it loud in the dashboard).
5. **EvalGen.** Per issue, generate an eval file: representative inputs (sanitized from real traces), assertion type chosen automatically (deterministic if the failure is structural, judge+rubric if semantic), and metadata linking back to the issue. Output is human-editable YAML plus a generated pytest module. `regress run` executes them against recorded traces (replay) or a live endpoint.
6. **Calibrator.** Dashboard flow to hand-label N sampled judge verdicts; compute Cohen's kappa judge-vs-human, plot agreement by rubric, and auto-suggest threshold changes. `regress calibrate --report` emits a markdown report. This component is small but is the resume differentiator — do not cut it.
7. **CI gate.** `regress run --gate` returns nonzero on regression with a two-proportion significance test (not raw pass-rate diff — flakiness awareness matters). Ship a composite GitHub Action and a copy-paste workflow snippet in the README.
8. **Dashboard.** React 18 + TypeScript + Tailwind (same stack as AgentMesh dashboard — reuse patterns). Views: trace explorer, issue board (kanban by lifecycle state), eval suite, calibration report. Served as static files by the FastAPI app; no separate deployment.

### Data model (minimum)

`traces(id, root_span, app, started_at, cost, latency, status)` · `spans(id, trace_id, kind, model, input, output, attrs)` · `scores(id, span_id|trace_id, source: deterministic|judge|human, name, value, rubric, reasoning)` · `issues(id, title, description, state, centroid_vector, created_at, resolved_at)` · `issue_traces(issue_id, trace_id)` · `evals(id, issue_id, path, type, created_at)` · `labels(id, score_id, human_value, labeler, created_at)`

## Stack

Python 3.11, FastAPI, SQLAlchemy (SQLite default / Postgres+pgvector), sentence-transformers (bge-small), HDBSCAN (scikit-learn/hdbscan), Click CLI, httpx, pydantic v2. Judges via a provider-agnostic thin client (OpenAI-compatible interface; default to a cheap hosted model, allow Ollama for fully-local). Frontend: React 18 + TS + Tailwind + Vite. Packaging: `pyproject.toml`, publish to PyPI as `regress-ai`. Docker + docker-compose. GitHub Actions CI from Phase 1.

## MASTER_PLAN

Commit at the end of each phase (checkpoint-commits skill). Each phase ends with tests green and README updated for what exists.

- **Phase 0 — Skeleton (day 1).** Repo, pyproject, CLI stub (`regress up` serves hello), CI pipeline, license (Apache-2.0), README with the one-liner and architecture diagram. Ship the skeleton to GitHub immediately.
- **Phase 1 — Ingest + Store.** OTLP endpoint, GenAI-convention parsing, SQLite storage, `regress traces` CLI listing. Tests: golden OTLP payloads from real exporters (record fixtures from Langfuse/OTel SDK output).
- **Phase 2 — instrument() SDK.** Patch openai + anthropic, `@task`, `feedback()`. Demo script in `examples/quickstart.py`. This unlocks the 3-step README flow — record the demo GIF now.
- **Phase 3 — Scorer.** Deterministic checks + judge with stored rubrics/reasoning. Config via `regress.yaml` (optional).
- **Phase 4 — Clusterer + Issues.** Embeddings, HDBSCAN, LLM titling, lifecycle states incl. `regressed` detection.
- **Phase 5 — EvalGen + CI gate.** YAML evals, `regress run`, significance-tested `--gate`, GitHub Action. This is the demo-able core loop — cut a tagged v0.1.0 release here.
- **Phase 6 — Calibrator.** Labeling flow, kappa report, `regress calibrate`.
- **Phase 7 — Dashboard.** Trace explorer, issue kanban, calibration view. v0.2.0.
- **Phase 8 — Dogfood + case study.** Run AgentMesh's 9-agent incident-response deployment and ARGUS's adversarial battery through Regress. Write `docs/case-study.md` with real numbers: issues found, evals generated, a deliberately re-introduced bug caught by the gate. These numbers become the resume bullets.

## Quality bar

- pytest throughout; target the AgentMesh standard (200+ tests, CI-green) by v0.2.0. Every bug found during dogfooding becomes a regression test — the project should practice what it preaches.
- Type hints everywhere, mypy in CI, ruff for lint/format.
- README must contain: 3-step quickstart, GIF, architecture diagram, "why not just Langfuse/Braintrust" honesty section, and the case-study link. No feature that isn't documented.
- Sanitize any real trace content before it lands in generated evals or docs (strip emails, keys, names) — there's a `sanitize()` pass in EvalGen from day one.

## Non-goals (v0)

No hosted/multi-tenant SaaS, no auth beyond a single optional bearer token, no prompt-management/playground features, no fine-tuning loops, no support for non-GenAI OTel traffic, no Kubernetes manifests. Say no in the README so the scope reads as intentional.

## Metrics to capture along the way (for resume + case study)

- Time-to-first-trace for a new user (target: < 5 min, measure honestly).
- On the AgentMesh dogfood: # traces ingested, # issues auto-discovered, # evals generated, judge-vs-human kappa after calibration, and one concrete regression the CI gate caught.
- Judge cost per 1k traces at default settings.
