# How Regress works

Regress turns a production failure into a committed regression test,
automatically. A trace comes in, gets scored, similar failures cluster into an
issue, that issue becomes an eval, and the eval gates your next deploy — with a
calibration loop keeping the judge that drives all of it honest.

**▶ [Interactive walkthrough](https://claude.ai/code/artifact/776245a1-78bb-4416-9512-a44ab06f8d4d)** — a visual, stage-by-stage tour with the design reasoning behind each piece.

## The pipeline

```
production trace → scored failure → clustered issue → generated eval → CI gate
```

| # | Stage | Command | What happens |
|---|-------|---------|--------------|
| 1 | **Ingest** | `instrument()` | One line in your app records every LLM call as a trace, over the open OpenTelemetry GenAI standard. Any OTel exporter works too — no lock-in. |
| 2 | **Score** | `regress score` | Two tiers decide what's a failure: cheap deterministic checks (schema, regex, refusal, latency) first, then an LLM judge with a rubric for the semantic cases. Every verdict stores its rubric, model, and reasoning. |
| 3 | **Cluster** | `regress cluster` | Failing traces are embedded (failure reason + question + answer) and grouped with HDBSCAN into **Issues**. A new failure landing in a *resolved* issue flips it to **regressed** — a fix that didn't hold. |
| 4 | **EvalGen** | `regress evalgen` | Each issue becomes a sanitized, human-editable YAML eval + pytest module in your repo. The assertion is chosen from whatever caught the failure. |
| 5 | **Gate** | `regress run --gate` | Replays evals against your live app and blocks the deploy on a **statistically significant** drop (a two-proportion z-test, not a raw diff) — so flaky cases don't fail the build, but real regressions do. |
| 6 | **Calibrate** | `regress calibrate` | The judge drives everything above, so you hand-label a sample and get **Cohen's kappa** (judge vs. human) — which exposes a judge that looks accurate but isn't actually discriminating. |

## See it in action

- **[Case study](case-study.md)** — the full loop run against a real LlamaIndex
  RAG over SQuAD, with the numbers it produced.
- **[Usage guide](usage.md)** — the complete command and flag reference.
