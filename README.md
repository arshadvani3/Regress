# Regress

**Your agent's production failures become its regression suite. Automatically.**

Regress is an open-source **failure-to-eval compiler**. It closes the loop that
every LLM observability vendor admits is open:

```
production trace → clustered failure → tracked issue → auto-generated eval → CI regression gate
```

...as a single self-hostable tool you can adopt in under 5 minutes.

> **Status: pre-alpha (Phase 6).** The architecture below is the target shape.
> Today `regress up` serves a health check and a real OTLP/HTTP ingest
> endpoint (`POST /v1/traces`, protobuf or JSON) that parses GenAI semantic
> convention spans into SQLite. `regress traces` lists what's been ingested.
> `from regress import instrument` patches the `openai` and `anthropic`
> clients to emit those spans automatically, `@task` groups a function's
> calls into one trace, and `feedback()` attaches a score to a trace after
> the fact. `regress score` runs deterministic checks (JSON-schema, regex/
> exact-match, tool-call args, latency/cost thresholds, refusal detection)
> and an optional LLM-judge over ingested spans, configured via an optional
> `regress.yaml`. `regress cluster` embeds scored-bad traces, groups them
> with HDBSCAN, and writes each cluster up as an Issue with an LLM title and
> description — including detecting when a `resolved` issue's failure
> pattern comes back as `regressed`. `regress evalgen` turns each issue into
> a sanitized, human-editable YAML eval + pytest module, and `regress run
> evals/ --gate` replays them (or hits a live endpoint) and fails the build
> only on a statistically significant regression. `regress calibrate` samples
> judge verdicts for hand-labeling, computes Cohen's kappa judge-vs-human
> (overall and per rubric), and suggests a `score` threshold that would
> agree with humans better than the judge's own pass/fail call. See
> [MASTER_PLAN](#roadmap) for what's built vs. planned.

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
     shipped as a reusable GitHub Action (.github/actions/gate)
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
- [x] **Phase 3 — Scorer.** Deterministic checks + LLM-judge with stored rubrics.
- [x] **Phase 4 — Clusterer + Issues.** Embeddings, HDBSCAN, lifecycle states.
- [x] **Phase 5 — EvalGen + CI gate.** YAML evals, `regress run`, GitHub Action. (v0.1.0)
- [x] **Phase 6 — Calibrator.** Labeling flow, judge-vs-human kappa report.
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

Once traces are ingested, score them with the two-tier Scorer. With no
config, `regress score` runs the zero-config `not_refusal` check against
every unscored span:

```bash
regress score
```

For anything else — schema validation, thresholds, or a judge rubric —
add an optional `regress.yaml`:

```yaml
judge:
  model: gpt-4o-mini          # any OpenAI-compatible endpoint, incl. Ollama
  base_url: https://api.openai.com/v1

checks:
  - check: not_refusal
  - check: latency_under
    name: fast_response
    max_ms: 2000
  - check: judge_rubric
    name: helpfulness
    rubric: "Does the response directly answer the user's question?"
```

```bash
regress score --config regress.yaml
```

Every score is stored with its source (`deterministic` | `judge` | `human`)
and, for judge verdicts, the rubric, model, and raw reasoning — so verdicts
stay auditable. `--rescore` re-runs checks on spans that already have scores.

Once enough traces are scored bad, cluster them into Issues:

```bash
pip install 'regress-ai[cluster]'   # sentence-transformers + scikit-learn
regress cluster
```

For each trace with a failed score, `regress cluster` embeds (failure
reason + last user message + final output) with a local `bge-small-en-v1.5`
model, groups similar failures with HDBSCAN, and asks the judge model to
write a title and description for each cluster. A cluster that matches an
existing issue adds its traces there; a cluster that matches a **resolved**
issue flips it to **regressed** — the loudest signal in the tool, because it
means a fix didn't hold:

```
Considered 42 scored-bad trace(s), found 3 cluster(s).
  new issues: 1
  updated issues: 1
  REGRESSED issues: 1
    - 'Refuses valid refund requests' (a1b2c3d4) is failing again
```

`sentence-transformers` isn't a core dependency — it pulls in `torch`,
which would blow past the "5 minutes to first trace" quickstart — so
clustering is the `cluster` extra, installed only when you need it.

Turn issues into committed regression tests:

```bash
regress evalgen        # writes evals/<issue-slug>.yaml + test_<issue-slug>.py
```

Each eval picks its assertion from whatever actually caught the failure —
a judge rubric if a judge check failed, `not_refusal` if that's what
tripped, or (for checks whose original parameters aren't recoverable from
the stored score, like `latency_under`'s threshold) a per-case pin on the
exact bad output. Representative inputs and outputs are sanitized
(`sanitize()` strips emails, phone numbers, API-key-shaped tokens, and
common name introductions) before they ever touch a file. The generated
YAML is the source of truth; the paired pytest module is a thin shim so
`pytest evals/` works standalone too, per CLAUDE.md's "everything is also
a file" principle.

Run the suite two ways:

```bash
regress run evals/                              # replay: confirms each eval still fails against its own recorded bad output
regress run evals/ --against http://localhost:8000/predict   # live: POST each case's input, score the fresh response
```

`--against` a live endpoint is the real regression check — a passing case
means the fix held. Add `--gate` to fail the build on a regression:

```bash
regress run evals/ --against http://localhost:8000/predict --gate
```

The gate is a **two-proportion significance test**, not a raw pass-rate
diff — a single flaky case dropping the pass rate from 100% to 95% won't
fail the build, but a systemic drop from 95% to 50% will (p < 0.001 in
that case). The baseline is a small `.regress-baseline.json` next to your
evals; commit it alongside `evals/` so CI has something to compare
against, or restore it from cache if you'd rather not commit it.

A composite GitHub Action wraps this — copy into your workflow:

```yaml
name: Regress gate
on: [pull_request]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: arshadvani3/Regress/.github/actions/gate@main
        with:
          against: https://staging.example.com/predict
          judge-api-key: ${{ secrets.REGRESS_JUDGE_API_KEY }}
```

The judge is doing real work throughout this loop — every `judge_rubric` score
feeds clustering, eval generation, and the gate — so it's worth knowing how
much to trust it. The Calibrator hand-labels a sample of judge verdicts and
reports judge-vs-human agreement:

```bash
regress calibrate --label 20 --labeler you@example.com
```

```
[1/20] rubric: Does the response directly answer the user's question?
  output: I'm sorry, but I can't help with that.
  judge verdict: FAIL (score=0.10) — response refuses instead of answering
  Does this response actually pass? [y/N]:
```

Sampling is stratified by rubric, so a small N still covers every rubric
in use rather than exhausting whichever one has the most scores. Already-
labeled scores are skipped by default (`--include-labeled` to re-label for
inter-labeler agreement). Then:

```bash
regress calibrate --report
```

```
## Overall
| Scope | N | Agreement | Cohen's kappa | Judge pass rate | Human pass rate |
|---|---|---|---|---|---|
| Overall | 20 | 85.0% | 0.690 (substantial) | 45.0% | 40.0% |
```

Kappa, not raw agreement — two raters can "agree" 95% of the time by both
just saying "pass" almost always, with zero real signal, whenever most
cases are easy. Kappa corrects for that using the judge's and human's own
pass-rate marginals, broken down overall and per rubric so you can see
which rubrics the judge is well-calibrated on and which are noise. It also
sweeps `Score.value` cutoffs to suggest a threshold that agrees with your
labels better than the judge's own `passed` call, when one exists.
`--label` and `--report` combine in one invocation; `--report` alone
prints to stdout, `--report path.md` writes a file.

## License

Apache-2.0. See [LICENSE](LICENSE).
