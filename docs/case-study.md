# Case study: dogfooding Regress on a LlamaIndex RAG

This is the full failure-to-eval loop run end to end against a real
retrieval-augmented-generation app, with the numbers it produced. Nothing
here is synthetic: the app makes real OpenAI calls, the failures are real, and
every count comes out of the SQLite DB the run wrote.

## Setup

- **App under test:** a [LlamaIndex](https://github.com/run-llama/llama_index)
  RAG pipeline (`VectorStoreIndex` + query engine, `gpt-4o-mini` for
  synthesis, `text-embedding-3-small` for retrieval), non-streaming.
- **Corpus + questions:** [SQuAD v1.1](https://rajpurkar.github.io/SQuAD-explorer/)
  — 60 Wikipedia passages indexed, 100 questions asked, each with a gold
  reference answer. Ground truth is what makes the scoring and the regression
  demo honest rather than vibe-based.
- **Instrumentation:** one line — `from regress import instrument; instrument()`
  — with `REGRESS_ENDPOINT` pointed at a local `regress up`. LlamaIndex routes
  its LLM calls through `llama_index.llms.openai`, which bottoms out in the
  same `openai.resources.chat.completions.Completions` class `instrument()`
  patches, so every RAG call surfaced with no changes to LlamaIndex itself.
- **Judge/embedding cost for the entire study:** under $0.05. RAG chat calls
  across both runs used ~96k input / ~5.7k output tokens (~$0.02 on
  `gpt-4o-mini`); scoring and clustering ran on the same cheap tier and a
  local `bge-small` embedding model.

## The loop, with real numbers

| Stage | Command | Result |
|---|---|---|
| Ingest | `instrument()` + the RAG batch | **200 traces** (100 real `chat` RAG traces + 100 gradeable eval spans) |
| Score | `regress score` | **79/100** answers correct vs. SQuAD gold — **21 real failures** |
| Cluster | `regress cluster` | 21 failures → **2 Issues**, LLM-titled |
| EvalGen | `regress evalgen` | **8 regression cases** across 2 eval files (YAML + pytest) |
| Calibrate | `regress calibrate` + 40 gold labels | **Cohen's κ = 0.435** (moderate), 80% raw agreement |
| Gate | two-proportion z-test | healthy **79%** vs. degraded **47%** → **regression, p < 0.00001** |

## What the clusterer found

The 21 failing traces grouped into two distinct, correctly-named issues:

1. **"Incorrect factual information provided"** (6 traces) — plausible but wrong
   substitutions. E.g. *"What is the name of another compelling continuation of
   the Fermat primality test?"* → gold *"Solovay-Strassen tests"*, RAG answered
   *"Miller-Rabin test"*. And a Super Bowl 50 question whose gold was
   *"Ted Ginn Jr."* got *"Jerricho Cotchery"*.
2. **"Provide concise and direct answers"** (3 traces) — over-verbose answers
   that bury or diverge from the reference.

A retrieval miss was vivid enough to quote: asked *"What was a first for this
network?"* (gold: hosts made responsible for reliable delivery), the RAG
retrieved the wrong passage and answered about the *"TGIF" TV comedy block*.

## The regression the gate caught

The generated evals become the regression suite. To prove the gate does its
job, the RAG was deliberately degraded — retrieval `top_k` dropped from 3 to 1
and questions truncated to half length — and the same 100 questions re-run and
re-scored:

- **Healthy:** 79/100 pass
- **Degraded:** 47/100 pass
- `two_proportion_z_test(79, 100, 47, 100)` → **p < 0.00001, regression = True**

Crucially, this is a *significance* test, not a raw diff. A 4-point drop to
75/100 (sampling noise) is **not** flagged (p = 0.25); only the real 32-point
drop is. That's the whole point of the gate — a single flaky case can't fail
your build, but a systemic quality drop will.

## A bug the dogfood found in Regress itself

Per the project's own principle ("every bug found during dogfooding becomes a
regression test"): during clustering, `gpt-4o-mini` sometimes returned a JSON
*array* of title/description objects instead of the single object the titler
prompt asked for, and the parser crashed with a `TypeError`, blanking a
cluster's title. Fixed in `src/regress/clustering/titler.py` (coalesce a list
response to its first element) with two regression tests in
`tests/test_clustering_titler.py`.

## Honest caveats

- **Judge non-determinism at the margin.** On eval replay, 7 of 8 cases
  correctly re-failed against their own recorded bad output; 1 flipped to pass
  on re-judging. This is expected LLM-judge variance and is exactly why the
  gate uses a significance test rather than exact-match.
- **The judge is stricter than gold-string matching.** It passed 72.5% of the
  calibration sample vs. 82.5% for SQuAD-style gold matching — it fails some
  answers that contain the gold text but pad it with extra (possibly wrong)
  detail. κ = 0.435 reflects this genuine, explainable disagreement, not a
  broken judge.
- **Grading shape.** Because Regress's judge scores span *output* text, each
  question emitted a companion span bundling the question, gold answer, and RAG
  answer so a single rubric could grade against ground truth. The realistic
  `chat` traces are what clustering and eval generation consumed.

## The loop is all stock commands

The RAG driver (LlamaIndex + SQuAD) is a harness, not part of Regress — but
once traces are flowing in, every stage above is a stock Regress command,
unchanged from what any user runs:

```bash
# with instrument() active in the app and REGRESS_ENDPOINT set at `regress up`:
regress score   --config regress.yaml   # judge answers vs. a rubric
regress cluster --min-cluster-size 3     # group failures into Issues
regress evalgen --dir evals              # write YAML + pytest regression cases
regress calibrate --report               # Cohen's kappa, after labeling a sample
regress run evals/ --gate                # significance-tested CI gate
```
