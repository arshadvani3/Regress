# Regress usage guide

The complete command reference. For the 30-second version, see the
[README quickstart](../README.md#quickstart). Every command below is a stock
`regress` subcommand — run `regress --help` or `regress <cmd> --help` for the
authoritative flag list.

- [regress demo](#regress-demo)
- [regress init](#regress-init)
- [1. Ingest traces](#1-ingest-traces)
- [2. Score](#2-score)
- [3. Cluster into issues](#3-cluster-into-issues)
- [4. Generate evals](#4-generate-evals)
- [regress analyze — do 2-4 in one step](#regress-analyze--do-2-4-in-one-step)
- [5. Run + gate in CI](#5-run--gate-in-ci)
- [6. Calibrate the judge](#6-calibrate-the-judge)
- [The dashboard](#the-dashboard)
- [Configuration reference](#configuration-reference)

---

## regress demo

The fastest way to see what Regress does. Seeds a small, fictional
support-bot scenario — failing traces already scored and clustered into two
Issues (one `active`, one `regressed`, to show the lifecycle) — so `regress
up`'s dashboard is populated the instant you install, with nothing to
instrument first.

```bash
regress demo          # load the sample
regress up            # then open http://localhost:8990 to explore it
regress demo --reset  # remove it when you're done
```

Demo rows are tagged internally, so `--reset` removes exactly them and leaves
any real data you've ingested untouched. Running `regress demo` again while
it's already loaded is a no-op (it tells you to `--reset` first).

---

## regress init

Scaffolds a starter `regress.yaml` in the current directory: the deterministic
checks (`not_refusal`, `latency_under`) uncommented and ready to run, plus a
menu of named judge rubrics commented out — uncomment the ones that fit your
app instead of writing a rubric from scratch.

```bash
regress init
regress init --path configs/regress.yaml   # write somewhere else
regress init --force                       # overwrite an existing file
```

The rubric menu: `response_quality` (the same one the zero-config default
uses), `answers_the_question`, `no_hallucination`, `stays_on_topic`,
`not_toxic`, `follows_format`. Each is a complete, ready-to-use rubric string
— delete the `#` and the two lines above it to enable one.

---

## 1. Ingest traces

Regress ingests OpenTelemetry **GenAI-convention** spans over OTLP/HTTP at
`POST /v1/traces` (protobuf or JSON). Two ways to get spans in:

**Option A — `instrument()`** patches the `openai` and `anthropic` clients so
every call exports automatically, with no other code changes:

```python
from regress import instrument, task, feedback

instrument()  # patches openai + anthropic clients in this process

@task(name="answer_question")
def answer(question: str) -> str:
    response = client.chat.completions.create(model="gpt-4o-mini", messages=[...])
    return response.choices[0].message.content

# later, e.g. from a user thumbs-down in your app:
feedback(trace_id=trace_id, score=0.0, comment="wrong refund policy")
```

`@task` groups a whole function's calls (including nested SDK calls) into one
trace. `feedback()` attaches a human score to a trace after the fact. See
[examples/quickstart.py](../examples/quickstart.py) for a runnable version.

**Streaming works too.** `create(..., stream=True)` is captured transparently:
the streamed chunks are reassembled into one span (text, finish reason, and
token usage when the caller passes `stream_options={"include_usage": True}`),
emitted when the stream finishes. Your code is untouched — every chunk still
flows to you unchanged, and `with stream as s:` / `.close()` still work. Sync
and async streams are both handled.

**Option B — any OTLP exporter.** Already exporting OTel GenAI spans (Langfuse,
the OTel SDK, etc.)? Point it at `regress up` and skip `instrument()` entirely:

```bash
regress up &
curl -X POST http://localhost:8990/v1/traces \
  -H "Content-Type: application/x-protobuf" --data-binary @trace.pb
```

List what came in:

```bash
regress traces           # most recent first
regress traces --limit 50
```

> By default `instrument()` exports to `http://127.0.0.1:8990/v1/traces`.
> Override with the `REGRESS_ENDPOINT` env var.

---

## 2. Score

Two-tier scoring. With no `regress.yaml`, `regress score` always runs
`not_refusal` (free, no LLM), and — if an API key is available
(`OPENAI_API_KEY` or `REGRESS_JUDGE_API_KEY`) — also runs a built-in
`response_quality` judge check, so a first run finds real failures even
before you've written a rubric:

```bash
regress score
```

```
No regress.yaml found — running the built-in quality check (LLM judge,
gpt-4o-mini, ~1 API call/span). Add a regress.yaml to customize or silence.
Scored 12 span(s) against 2 check(s): 24 score(s).
```

With no key set, zero-config runs `not_refusal` only — no LLM call, no cost,
no notice. See [`regress init`](#regress-init) for scaffolding a
`regress.yaml` with more rubrics to choose from.

For anything else — schema validation, thresholds, or your own judge rubric —
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
regress score --config regress.yaml --rescore   # re-run on already-scored spans
```

**Deterministic checks:** `json_schema_valid`, `regex_match`, `exact_match`,
`tool_call_args_valid`, `latency_under`, `cost_under`, `not_refusal`.
**Judge check:** `judge_rubric` — rubric-based LLM-as-judge.

Every score is stored with its source (`deterministic` | `judge` | `human`)
and, for judge verdicts, the rubric, model, and raw reasoning — so verdicts
stay auditable.

---

## 3. Cluster into issues

Group scored-bad traces into tracked Issues. Requires the `cluster` extra
(local embeddings, no API cost):

```bash
pip install 'regress-ai[cluster]'   # sentence-transformers + scikit-learn
regress cluster
regress cluster --min-cluster-size 5   # default is 3
```

For each trace with a failed score, `regress cluster` embeds (failure reason +
last user message + final output) with a local `bge-small-en-v1.5` model,
groups similar failures with HDBSCAN, and asks the judge model to write a title
and description per cluster.

A cluster that matches an existing issue adds its traces there; a cluster that
matches a **resolved** issue flips it to **regressed** — the loudest signal in
the tool, because it means a fix didn't hold:

```
Considered 42 scored-bad trace(s), found 3 cluster(s).
  new issues: 1
  updated issues: 1
  REGRESSED issues: 1
    - 'Refuses valid refund requests' (a1b2c3d4) is failing again
```

**Early on you may not have enough failures yet.** Clustering never invents
patterns from thin data — if you have fewer failures than
`--min-cluster-size`, it tells you exactly how many you have and what to do
(run more traffic, or retry at a lower floor):

```
Only 2 scored-bad traces found (need at least 3 similar ones to form a
reliable cluster). With this few, retry at `--min-cluster-size 2` to group
them, or keep running your app to accumulate more.
```

`--min-cluster-size` must be at least 2 (a cluster needs two similar
failures). This is why generated evals are trustworthy: an eval only ever
comes from a real, repeated failure pattern — never a one-off.

> `sentence-transformers` pulls in `torch`, which would blow past the "5
> minutes to first trace" quickstart — so clustering is an opt-in extra.

---

## 4. Generate evals

Turn issues into committed regression tests:

```bash
regress evalgen                    # writes to ./evals/
regress evalgen --dir tests/evals  # custom directory
regress evalgen --state all        # every issue state, not just active
```

Each eval picks its assertion from whatever actually caught the failure — a
judge rubric if a judge check failed, `not_refusal` if that's what tripped, or
(for checks whose parameters aren't recoverable from the stored score, like
`latency_under`'s threshold) a per-case pin on the exact bad output.

Representative inputs and outputs are **sanitized** (`sanitize()` strips
emails, phone numbers, API-key-shaped tokens, and common name introductions)
before they ever touch a file. The generated YAML is the source of truth; the
paired `test_<slug>.py` module is a thin shim so `pytest evals/` works
standalone too.

---

## regress analyze — do 2-4 in one step

Score, cluster, and evalgen are three separate commands so each one works
standalone — but for the common path ("I just ingested traces, get me to
evals"), `regress analyze` runs all three in sequence and prints one report:

```bash
regress analyze                              # score -> cluster -> evalgen
regress analyze --config regress.yaml        # same --config as `regress score`
regress analyze --min-cluster-size 5         # same flag as `regress cluster`
regress analyze --dir tests/evals            # same --dir as `regress evalgen`
```

```
Scored 12 span(s) against 2 check(s): 24 score(s), 4 failing.
Clustered 4 scored-bad trace(s) into 1 cluster(s): 1 new, 0 updated, 0 regressed.
Generated 1 eval(s) in evals/:
  refuses-refund-requests-a1b2c3d4.yaml — 'Refuses valid refund requests' (4 case(s))
```

`regress cluster` and `regress evalgen` still work exactly as documented
above if you want to run (or re-run) a step on its own — `analyze` is
additive, not a replacement. It generates evals for **active** issues only,
same as bare `regress evalgen` (no `--state` flag; use the standalone
command for `--state all` or other states).

---

## 5. Run + gate in CI

Run the suite two ways:

```bash
# Replay: confirm each eval still fails against its own recorded bad output
regress run evals/

# Live: POST each case's input to your app, score the fresh response
regress run evals/ --against http://localhost:8000/predict
```

`--against` a live endpoint is the real regression check — a passing case means
the fix held. Add `--gate` to fail the build on a regression:

```bash
regress run evals/ --against http://localhost:8000/predict --gate
regress run evals/ --against ... --gate --alpha 0.01   # stricter threshold
```

The gate is a **two-proportion significance test**, not a raw pass-rate diff —
a single flaky case dropping the pass rate from 100% to 95% won't fail the
build, but a systemic drop from 95% to 50% will. The baseline is a small
`.regress-baseline.json` next to your evals; commit it alongside `evals/` (or
restore it from CI cache).

The live endpoint contract: Regress `POST`s `{"input": <case input>}` and
expects `{"output": "<response>"}` back.

### GitHub Action

A composite Action wraps the gate — copy into your workflow:

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

---

## 6. Calibrate the judge

The judge drives clustering, eval generation, and the gate — so it's worth
knowing how much to trust it. The Calibrator hand-labels a sample of judge
verdicts and reports judge-vs-human agreement:

```bash
regress calibrate --label 20 --labeler you@example.com
```

```
[1/20] rubric: Does the response directly answer the user's question?
  output: I'm sorry, but I can't help with that.
  judge verdict: FAIL (score=0.10) — response refuses instead of answering
  Does this response actually pass? [y/N]:
```

Sampling is stratified by rubric, so a small N covers every rubric in use.
Already-labeled scores are skipped by default (`--include-labeled` to re-label
for inter-labeler agreement). Then produce the report:

```bash
regress calibrate --report            # markdown to stdout
regress calibrate --report report.md  # write to a file
```

```
## Overall
| Scope   | N  | Agreement | Cohen's kappa       | Judge pass rate | Human pass rate |
|---------|----|-----------|---------------------|-----------------|-----------------|
| Overall | 20 | 85.0%     | 0.690 (substantial) | 45.0%           | 40.0%           |
```

**Why kappa, not raw agreement?** Two raters can "agree" 95% of the time by
both saying "pass" almost always, with zero real signal, whenever most cases
are easy. Cohen's kappa corrects for that using each rater's own pass-rate
marginals — broken down overall and per rubric, so you can see which rubrics
the judge is calibrated on and which are noise. The report also sweeps
`Score.value` cutoffs to suggest a threshold that agrees with your labels
better than the judge's own `passed` call, when one exists.

`--label` and `--report` can be combined in one invocation.

---

## The dashboard

`regress up` serves a React dashboard at `http://localhost:8990` — no separate
frontend process, no build step for end users (it ships prebuilt in the wheel).
Three views:

- **Traces** — a sortable list; click through to a trace's full span/message
  timeline with every score inline.
- **Issues** — a kanban board grouped by lifecycle state (active / regressed /
  resolved); each card links to its member traces and generated eval files.
- **Calibration** — the same labeling flow as `regress calibrate --label` and
  the same kappa/threshold report as `--report`, sharing the exact
  `regress.calibrate.*` code the CLI uses.

The dashboard talks to a read-only JSON API under `/api/*` (`src/regress/api/`);
the only write route is `POST /api/labels`, the browser equivalent of
`regress calibrate --label`.

---

## Configuration reference

| Env var | Purpose | Default |
|---|---|---|
| `REGRESS_DB_URL` | Storage backend | `sqlite:///regress.db` |
| `REGRESS_ENDPOINT` | Where `instrument()` exports OTLP spans | `http://127.0.0.1:8990/v1/traces` |
| `REGRESS_JUDGE_API_KEY` | Judge model API key (falls back to `OPENAI_API_KEY`) | — |
| `REGRESS_JUDGE_BASE_URL` | Judge endpoint when no `regress.yaml` sets one (e.g. a local Ollama) | `https://api.openai.com/v1` |
| `OPENAI_API_KEY` | Used by `instrument()`-patched calls and the judge | — |

`regress.yaml` (all keys optional):

```yaml
judge:
  model: gpt-4o-mini
  base_url: https://api.openai.com/v1   # any OpenAI-compatible endpoint

checks:
  - check: <check-name>     # see "Score" above for the full list
    name: <label>           # optional; defaults to the check name
    rubric: "<text>"        # judge_rubric only
    # ...plus any check-specific params (max_ms, cost thresholds, schema, etc.)
```
